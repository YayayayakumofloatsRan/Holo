from pathlib import Path

import pytest

from holo_host.memory_admin import MEMORY_RESET_CONFIRMATION, MemoryResetPermissionError, reset_holo_memory


def _seed_memory_root(root: Path) -> None:
    memory_dir = root / "holo_memory_library" / "memories"
    memory_dir.mkdir(parents=True, exist_ok=True)
    (memory_dir / "memory_store.jsonl").write_text('{"id":"memory-1"}\n', encoding="utf-8")
    (memory_dir / "conversation_archive.jsonl").write_text('{"id":"archive-1"}\n', encoding="utf-8")
    runtime = root / ".holo_runtime"
    (runtime / "milvus").mkdir(parents=True, exist_ok=True)
    (runtime / "mind_graph.sqlite3").write_bytes(b"mind graph")
    (runtime / "mind_graph.sqlite3-wal").write_bytes(b"wal")
    (runtime / "milvus" / "memory_fabric.db").write_bytes(b"vector")
    (runtime / "visual_ingest_queue.jsonl").write_text('{"id":"visual-1"}\n', encoding="utf-8")
    (root / ".holo_host.toml").write_text("[runtime]\napi_port=8004\n", encoding="utf-8")


def test_reset_memory_requires_wsl_even_for_dry_run(tmp_path: Path) -> None:
    _seed_memory_root(tmp_path)

    with pytest.raises(MemoryResetPermissionError):
        reset_holo_memory(
            repo_root=tmp_path,
            confirm=MEMORY_RESET_CONFIRMATION,
            reason="operator test",
            dry_run=True,
            wsl_environment=False,
        )


def test_reset_memory_requires_exact_confirmation(tmp_path: Path) -> None:
    _seed_memory_root(tmp_path)

    with pytest.raises(ValueError, match=MEMORY_RESET_CONFIRMATION):
        reset_holo_memory(
            repo_root=tmp_path,
            confirm="yes",
            reason="operator test",
            dry_run=True,
            wsl_environment=True,
        )


def test_reset_memory_dry_run_does_not_write_backup_or_clear_files(tmp_path: Path) -> None:
    _seed_memory_root(tmp_path)

    report = reset_holo_memory(
        repo_root=tmp_path,
        confirm=MEMORY_RESET_CONFIRMATION,
        reason="operator dry run",
        dry_run=True,
        wsl_environment=True,
    )

    assert report["status"] == "dry_run"
    assert report["copied"] == []
    assert not Path(str(report["backup_dir"])).exists()
    assert (tmp_path / "holo_memory_library" / "memories" / "memory_store.jsonl").read_text(
        encoding="utf-8"
    ) == '{"id":"memory-1"}\n'
    assert (tmp_path / ".holo_runtime" / "mind_graph.sqlite3").exists()
    assert (tmp_path / ".holo_runtime" / "milvus" / "memory_fabric.db").exists()


def test_reset_memory_snapshots_and_clears_memory_stores_only_from_wsl(tmp_path: Path) -> None:
    _seed_memory_root(tmp_path)

    report = reset_holo_memory(
        repo_root=tmp_path,
        confirm=MEMORY_RESET_CONFIRMATION,
        reason="operator requested reset",
        wsl_environment=True,
    )

    assert report["status"] == "reset"
    assert report["wsl_only"] is True
    backup_dir = Path(str(report["backup_dir"]))
    assert backup_dir.exists()
    assert (backup_dir / "memory_store.jsonl").read_text(encoding="utf-8") == '{"id":"memory-1"}\n'
    assert (backup_dir / "conversation_archive.jsonl").read_text(encoding="utf-8") == '{"id":"archive-1"}\n'
    assert (backup_dir / "mind_graph.sqlite3").read_bytes() == b"mind graph"
    assert (backup_dir / "memory_reset_manifest.json").exists()

    assert (tmp_path / "holo_memory_library" / "memories" / "memory_store.jsonl").read_text(encoding="utf-8") == ""
    assert (tmp_path / "holo_memory_library" / "memories" / "conversation_archive.jsonl").read_text(encoding="utf-8") == ""
    assert not (tmp_path / ".holo_runtime" / "mind_graph.sqlite3").exists()
    assert not (tmp_path / ".holo_runtime" / "mind_graph.sqlite3-wal").exists()
    assert not (tmp_path / ".holo_runtime" / "milvus" / "memory_fabric.db").exists()
    assert not (tmp_path / ".holo_runtime" / "visual_ingest_queue.jsonl").exists()
    assert (tmp_path / ".holo_host.toml").exists()


def test_reset_memory_is_not_exposed_as_mobile_http_endpoint() -> None:
    reply_api = Path(__file__).resolve().parents[1] / "holo_host" / "reply_api.py"
    text = reply_api.read_text(encoding="utf-8")

    assert "/reset-memory" not in text
    assert "/memory-reset" not in text
