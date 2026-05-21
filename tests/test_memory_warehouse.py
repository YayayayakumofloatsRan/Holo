from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from holo_host import cli
from holo_host.memory_warehouse import memory_warehouse_report, write_memory_warehouse_artifacts


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")


def test_memory_warehouse_redacted_mode_shows_range_without_raw_text(tmp_path: Path) -> None:
    memory_dir = tmp_path / "holo_memory_library" / "memories"
    _write_jsonl(
        memory_dir / "memory_store.jsonl",
        [
            {
                "id": "memory-1",
                "created_at": "2026-04-02T00:00:00Z",
                "channel": "holo_cli",
                "thread_key": "holo_cli:main",
                "kind": "preference",
                "text": "private durable memory",
            }
        ],
    )
    _write_jsonl(
        memory_dir / "conversation_archive.jsonl",
        [{"id": "turn-1", "created_at": "2026-05-21T00:00:00Z", "user_text": "private archive turn"}],
    )

    report = memory_warehouse_report(tmp_path, include_raw=False)
    encoded = json.dumps(report, ensure_ascii=False)

    assert report["schema"] == "holo.memory_warehouse.v1"
    assert report["warehouse_start"] == "2026-04-02T00:00:00Z"
    assert report["warehouse_latest"] == "2026-05-21T00:00:00Z"
    assert report["privacy"]["raw_text_included"] is False
    assert "private durable memory" not in encoded
    assert "private archive turn" not in encoded


def test_memory_warehouse_raw_mode_includes_local_excerpts(tmp_path: Path) -> None:
    memory_dir = tmp_path / "holo_memory_library" / "memories"
    _write_jsonl(
        memory_dir / "memory_store.jsonl",
        [{"id": "memory-1", "created_at": "2026-04-02T00:00:00Z", "text": "visible durable memory"}],
    )

    report = memory_warehouse_report(tmp_path, include_raw=True, sample_limit=1)

    sample = report["stores"]["memory_store.jsonl"]["samples"]["first"][0]
    assert sample["text_fields"][0]["text"] == "visible durable memory"


def test_memory_warehouse_artifacts_write_json_and_html(tmp_path: Path) -> None:
    report = {
        "schema": "holo.memory_warehouse.v1",
        "repo_root": str(tmp_path),
        "generated_at": "2026-05-21T00:00:00Z",
        "warehouse_start": "2026-04-02T00:00:00Z",
        "warehouse_latest": "2026-05-21T00:00:00Z",
        "privacy": {"raw_text_included": False, "text_policy": "text hashes and lengths only"},
        "stores": {},
        "rag": {"inspect_mind": {}, "trace_hybrid": {}},
    }

    artifacts = write_memory_warehouse_artifacts(report, tmp_path / "out")

    assert Path(artifacts["json"]).exists()
    assert Path(artifacts["html"]).exists()
    assert "Holo Memory Warehouse" in Path(artifacts["html"]).read_text(encoding="utf-8")


def test_memory_warehouse_cli_requires_wsl_for_raw(monkeypatch, capsys) -> None:
    monkeypatch.setattr(cli, "_is_wsl_runtime", lambda: False)

    result = cli.main(["memory-warehouse", "--include-raw", "--confirm", "SHOW_HOLO_MEMORY_FROM_WSL"])

    assert result == 2
    assert json.loads(capsys.readouterr().out)["reason"] == "raw_memory_view_requires_wsl"


def test_memory_warehouse_cli_writes_report(monkeypatch, capsys, tmp_path: Path) -> None:
    monkeypatch.setattr(cli, "_is_wsl_runtime", lambda: True)
    monkeypatch.setattr(
        cli,
        "load_config",
        lambda config_path=None, repo_root=None: SimpleNamespace(runtime=SimpleNamespace(repo_root=tmp_path)),
    )
    monkeypatch.setattr(cli, "memory_doctor_report", lambda repo_root: {"biomimetic_health": {}})
    monkeypatch.setattr(
        cli,
        "_inspect_mind_payload",
        lambda *args, **kwargs: ({"tier": "deep_recall", "selected_memory_ids": ["memory-1"]}, "test"),
    )
    monkeypatch.setattr(
        cli,
        "_trace_hybrid_payload",
        lambda *args, **kwargs: ({"tier": "deep_recall", "recall_confidence": 1.0}, "test"),
    )

    result = cli.main(
        [
            "memory-warehouse",
            "--include-raw",
            "--confirm",
            "SHOW_HOLO_MEMORY_FROM_WSL",
            "--output-dir",
            str(tmp_path / "report"),
        ]
    )

    assert result == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "written"
    assert Path(payload["artifacts"]["html"]).exists()
