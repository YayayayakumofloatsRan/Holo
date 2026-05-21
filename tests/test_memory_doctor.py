from __future__ import annotations

import json
import sqlite3
from types import SimpleNamespace
from pathlib import Path

from holo_host import cli
from holo_host.memory_doctor import audit_jsonl_store, memory_doctor_report, route_latency_summary


def _write_jsonl(path: Path, rows: list[dict], *, invalid_tail: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows)
    if invalid_tail:
        payload += "{not-json}\n"
    path.write_text(payload, encoding="utf-8")


def _create_sqlite(path: Path, table_name: str = "mind_nodes") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as connection:
        connection.execute(f"CREATE TABLE {table_name} (id TEXT PRIMARY KEY)")
        connection.execute(f"INSERT INTO {table_name} VALUES ('node-1')")


def test_audit_jsonl_store_reports_integrity_without_raw_text(tmp_path: Path) -> None:
    store_path = tmp_path / "conversation_archive.jsonl"
    duplicate = {
        "id": "turn-1",
        "channel": "wechat",
        "thread_key": "Nemoqi",
        "text": "private text must not be echoed",
        "created_at": "2026-05-20T00:00:00Z",
    }
    _write_jsonl(
        store_path,
        [
            duplicate,
            duplicate,
            {"id": "turn-1", "channel": "wechat", "thread_key": "wechat:Nemoqi"},
            {"id": "turn-2", "channel": "holo_cli", "thread_key": "holo_cli:main"},
        ],
        invalid_tail=True,
    )

    report = audit_jsonl_store(store_path)

    assert report["valid_rows"] == 4
    assert report["invalid_rows"] == 1
    assert report["exact_duplicate_rows"] == 1
    assert report["duplicate_ids"] == {"turn-1": 3}
    assert report["top_channels"][0] == {"key": "wechat", "count": 3}
    assert "private text must not be echoed" not in json.dumps(report, ensure_ascii=False)


def test_route_latency_summary_deduplicates_adjacent_duplicate_log_lines(tmp_path: Path) -> None:
    log_path = tmp_path / ".holo_runtime" / "logs" / "reply_api.log"
    log_path.parent.mkdir(parents=True)
    line = "2026-05-21 reply route=deep_recall processor=main total_ms=100 chat=Nemoqi\n"
    log_path.write_text(
        line
        + line
        + "2026-05-21 reply route=fast processor=fast total_ms=20 chat=Nemoqi\n",
        encoding="utf-8",
    )

    summary = route_latency_summary(log_path)

    assert summary["total_records"] == 2
    assert summary["deduped_adjacent_records"] == 1
    assert summary["by_route"]["deep_recall"]["count"] == 1
    assert summary["by_route"]["deep_recall"]["p50_ms"] == 100
    assert summary["by_route"]["fast"]["avg_ms"] == 20


def test_memory_doctor_report_surfaces_biomimetic_health_and_thread_splits(tmp_path: Path) -> None:
    memory_dir = tmp_path / "holo_memory_library" / "memories"
    _write_jsonl(
        memory_dir / "conversation_archive.jsonl",
        [
            {
                "id": "archive-1",
                "channel": "wechat",
                "thread_key": "Nemoqi",
                "chat_name": "Nemoqi",
                "created_at": "2026-05-20T00:00:00Z",
                "text": "private archive text",
                "metadata": {
                    "route": "deep_recall",
                    "timing_ms": {"total_ms": 90000, "recall_reconstruct_ms": 87000},
                    "reply_bubbles": ["private bubble"],
                    "selected_memory_ids": ["memory-1"],
                },
            },
            {
                "id": "archive-2",
                "channel": "wechat",
                "thread_key": "wechat:Nemoqi",
                "chat_name": "Nemoqi",
                "created_at": "2026-05-21T00:00:00Z",
                "metadata": {"route": "fast", "timing_ms": {"total_ms": 120}},
            },
        ],
    )
    _write_jsonl(
        memory_dir / "memory_store.jsonl",
        [{"id": "memory-1", "thread_key": "wechat:Nemoqi", "created_at": "2026-04-01T00:00:00Z"}],
    )
    _create_sqlite(tmp_path / ".holo_runtime" / "mind_graph.sqlite3")
    _create_sqlite(tmp_path / ".holo_runtime" / "holo_host.sqlite3", table_name="threads")
    (tmp_path / ".holo_runtime" / "logs").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".holo_runtime" / "logs" / "reply_api.log").write_text(
        "2026-05-21 reply route=deep_recall processor=main total_ms=90000 chat=Nemoqi\n",
        encoding="utf-8",
    )

    report = memory_doctor_report(tmp_path)

    assert report["privacy"]["raw_text_included"] is False
    assert report["jsonl_stores"]["conversation_archive.jsonl"]["valid_rows"] == 2
    assert report["archive_metadata"]["route_counts"]["deep_recall"] == 1
    assert report["thread_identity"]["fragmentation_candidates"][0]["canonical_key"] == "wechat:Nemoqi"
    assert report["biomimetic_health"]["deep_recall_pressure"]["status"] in {"warn", "critical"}
    assert report["biomimetic_health"]["semantic_consolidation"]["status"] in {"warn", "critical"}
    assert report["recommendations"]
    assert "private archive text" not in json.dumps(report, ensure_ascii=False)
    assert "private bubble" not in json.dumps(report, ensure_ascii=False)


def test_memory_doctor_cli_dispatches_redacted_report(monkeypatch, capsys, tmp_path: Path) -> None:
    monkeypatch.setattr(
        cli,
        "load_config",
        lambda config_path=None: SimpleNamespace(runtime=SimpleNamespace(repo_root=tmp_path)),
    )
    monkeypatch.setattr(
        cli,
        "memory_doctor_report",
        lambda repo_root, vector_health=None: {
            "schema": "holo.memory_doctor.v1",
            "repo_root": str(repo_root),
            "privacy": {"raw_text_included": False},
            "vector": {},
        },
    )

    result = cli.main(["memory-doctor"])

    assert result == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema"] == "holo.memory_doctor.v1"
    assert payload["privacy"]["raw_text_included"] is False
    assert payload["vector"]["open_probe_source"] == "not_requested"
