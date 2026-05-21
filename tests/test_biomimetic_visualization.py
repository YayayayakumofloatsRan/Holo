from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace

from holo_host import cli
from holo_host.biomimetic_visualization import (
    build_biomimetic_visualization_payload,
    render_biomimetic_visualization_html,
    write_biomimetic_visualization,
)


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")


def _seed_repo(root: Path) -> None:
    memory_dir = root / "holo_memory_library" / "memories"
    _write_jsonl(
        memory_dir / "conversation_archive.jsonl",
        [
            {
                "id": "turn-1",
                "channel": "wechat",
                "thread_key": "ResearchThread",
                "created_at": "2026-05-21T00:00:00Z",
                "text": "private content must stay redacted",
                "metadata": {
                    "route": "fast",
                    "timing_ms": {"total_ms": 120},
                    "affect_state": {"valence": 0.4, "arousal": 0.2, "control": 0.7},
                },
            },
            {
                "id": "turn-2",
                "channel": "wechat",
                "thread_key": "wechat:ResearchThread",
                "created_at": "2026-05-21T00:01:00Z",
                "metadata": {
                    "route": "deep_recall",
                    "timing_ms": {"total_ms": 90000},
                    "selected_memory_ids": ["memory-1", "memory-2"],
                },
            },
        ],
    )
    _write_jsonl(
        memory_dir / "memory_store.jsonl",
        [{"id": "memory-1", "thread_key": "wechat:ResearchThread", "created_at": "2026-05-20T00:00:00Z"}],
    )
    _write_jsonl(memory_dir / "candidate_store.jsonl", [{"id": "candidate-1", "confidence": 0.8, "importance": 0.7}])
    _write_jsonl(memory_dir / "emotion_trace.jsonl", [{"id": "emotion-1", "valence": 0.5, "arousal": 0.4}])
    runtime = root / ".holo_runtime"
    (runtime / "logs").mkdir(parents=True, exist_ok=True)
    (runtime / "logs" / "reply_api.log").write_text(
        "2026-05-21 reply route=fast processor=micro_fast total_ms=120 chat=ResearchThread\n"
        "2026-05-21 reply route=deep_recall processor=subject_main total_ms=90000 chat=ResearchThread\n",
        encoding="utf-8",
    )
    with sqlite3.connect(runtime / "mind_graph.sqlite3") as connection:
        connection.execute("CREATE TABLE mind_nodes (id TEXT PRIMARY KEY, kind TEXT, label TEXT)")
        connection.execute("CREATE TABLE mind_edges (source_id TEXT, target_id TEXT, edge_type TEXT, weight REAL)")
        connection.execute("INSERT INTO mind_nodes VALUES ('memory-1', 'semantic_self_memory', 'private label')")
        connection.execute("INSERT INTO mind_nodes VALUES ('turn-1', 'episodic_turn', 'private turn')")
        connection.execute("INSERT INTO mind_edges VALUES ('turn-1', 'memory-1', 'recalls', 0.8)")


def test_biomimetic_visualization_payload_is_redacted_and_multilayer(tmp_path: Path) -> None:
    _seed_repo(tmp_path)

    payload = build_biomimetic_visualization_payload(tmp_path)

    assert payload["schema"] == "holo.biomimetic_visualization.v1"
    assert payload["privacy"]["raw_text_included"] is False
    assert len(payload["trajectory"]["frames"]) == 2
    assert payload["topology"]["nodes"]
    assert payload["topology"]["edges"]
    assert {"memory", "route", "health"}.issubset(set(payload["topology"]["layers"]))
    serialized = json.dumps(payload, ensure_ascii=False)
    assert "private content must stay redacted" not in serialized
    assert "private label" not in serialized


def test_render_biomimetic_visualization_html_has_interactive_canvases(tmp_path: Path) -> None:
    _seed_repo(tmp_path)
    payload = build_biomimetic_visualization_payload(tmp_path)

    html = render_biomimetic_visualization_html(payload)

    assert "<canvas id=\"phaseCanvas\"" in html
    assert "<canvas id=\"topologyCanvas\"" in html
    assert "<canvas id=\"sliceCanvas\"" in html
    assert "function drawTopology" in html
    assert "function drawPhase" in html
    assert "private content must stay redacted" not in html


def test_write_biomimetic_visualization_writes_html_and_payload(tmp_path: Path) -> None:
    _seed_repo(tmp_path)

    result = write_biomimetic_visualization(tmp_path, output_dir=tmp_path / "artifacts" / "stage100")

    html_path = Path(result["html_path"])
    payload_path = Path(result["payload_path"])
    assert html_path.exists()
    assert payload_path.exists()
    assert result["frame_count"] == 2
    assert json.loads(payload_path.read_text(encoding="utf-8"))["privacy"]["raw_text_included"] is False


def test_visualize_biomimetic_system_cli_dispatches(monkeypatch, capsys, tmp_path: Path) -> None:
    monkeypatch.setattr(
        cli,
        "load_config",
        lambda config_path=None: SimpleNamespace(runtime=SimpleNamespace(repo_root=tmp_path)),
    )
    monkeypatch.setattr(
        cli,
        "write_biomimetic_visualization",
        lambda repo_root, output_dir=None: {
            "status": "ok",
            "html_path": str(tmp_path / "artifacts" / "stage100" / "viewer.html"),
            "payload_path": str(tmp_path / "artifacts" / "stage100" / "payload.json"),
            "frame_count": 2,
            "node_count": 5,
            "edge_count": 4,
        },
    )

    result = cli.main(["visualize-biomimetic-system"])

    assert result == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "ok"
    assert payload["frame_count"] == 2
