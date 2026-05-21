from __future__ import annotations

import json
import os
import platform
import shutil
import uuid
from pathlib import Path
from typing import Any

from .common import utc_now

MEMORY_RESET_CONFIRMATION = "RESET_HOLO_MEMORY_FROM_WSL"

MEMORY_STORE_FILES = (
    "memory_store.jsonl",
    "working_store.jsonl",
    "candidate_store.jsonl",
    "conversation_archive.jsonl",
    "emotion_trace.jsonl",
    "callback_candidates.jsonl",
    "thought_stream.jsonl",
    "initiative_candidates.jsonl",
)

RUNTIME_MEMORY_FILES = (
    "mind_graph.sqlite3",
    "mind_graph.sqlite3-wal",
    "mind_graph.sqlite3-shm",
    "visual_ingest_queue.jsonl",
)

RUNTIME_MEMORY_DIRS = (
    "milvus",
)


class MemoryResetPermissionError(PermissionError):
    pass


def is_wsl_environment() -> bool:
    if os.environ.get("WSL_DISTRO_NAME") or os.environ.get("WSL_INTEROP"):
        return True
    if os.name != "posix":
        return False
    release = platform.release().lower()
    if "microsoft" in release or "wsl" in release:
        return True
    version_path = Path("/proc/version")
    try:
        version = version_path.read_text(encoding="utf-8", errors="ignore").lower()
    except OSError:
        return False
    return "microsoft" in version or "wsl" in version


def _require_wsl(wsl_environment: bool | None) -> None:
    allowed = is_wsl_environment() if wsl_environment is None else bool(wsl_environment)
    if not allowed:
        raise MemoryResetPermissionError("Holo memory reset is only allowed from the WSL brain environment.")


def _require_confirmation(confirm: str) -> None:
    if str(confirm or "").strip() != MEMORY_RESET_CONFIRMATION:
        raise ValueError(f"Refusing memory reset without exact confirmation: {MEMORY_RESET_CONFIRMATION}")


def _stamp() -> str:
    return f"{utc_now().replace(':', '-').replace('.', '-')}-{uuid.uuid4().hex[:8]}"


def _copy_if_exists(source: Path, destination: Path, copied: list[str]) -> None:
    if not source.exists():
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    if source.is_dir():
        shutil.copytree(source, destination)
    else:
        shutil.copy2(source, destination)
    copied.append(str(source))


def reset_holo_memory(
    *,
    repo_root: Path | str,
    confirm: str,
    reason: str,
    dry_run: bool = False,
    wsl_environment: bool | None = None,
) -> dict[str, Any]:
    _require_wsl(wsl_environment)
    _require_confirmation(confirm)

    root = Path(repo_root).resolve()
    memory_dir = root / "holo_memory_library" / "memories"
    runtime_dir = root / ".holo_runtime"
    backup_dir = runtime_dir / "memory_resets" / _stamp()
    copied: list[str] = []
    reset_files: list[str] = []
    removed_paths: list[str] = []

    for name in MEMORY_STORE_FILES:
        source = memory_dir / name
        if source.exists():
            reset_files.append(str(source))
            if not dry_run:
                _copy_if_exists(source, backup_dir / name, copied)

    for name in RUNTIME_MEMORY_FILES:
        source = runtime_dir / name
        if source.exists():
            removed_paths.append(str(source))
            if not dry_run:
                _copy_if_exists(source, backup_dir / name, copied)

    for name in RUNTIME_MEMORY_DIRS:
        source = runtime_dir / name
        if source.exists():
            removed_paths.append(str(source))
            if not dry_run:
                _copy_if_exists(source, backup_dir / name, copied)

    manifest = {
        "status": "dry_run" if dry_run else "reset",
        "created_at": utc_now(),
        "reason": str(reason or "").strip(),
        "wsl_only": True,
        "repo_root": str(root),
        "backup_dir": str(backup_dir),
        "memory_store_files": reset_files,
        "runtime_memory_paths": removed_paths,
        "copied": copied,
    }

    if dry_run:
        return manifest

    backup_dir.mkdir(parents=True, exist_ok=True)
    (backup_dir / "memory_reset_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    memory_dir.mkdir(parents=True, exist_ok=True)
    for name in MEMORY_STORE_FILES:
        (memory_dir / name).write_text("", encoding="utf-8")

    for path_text in removed_paths:
        path = Path(path_text)
        if path.is_dir():
            shutil.rmtree(path)
        elif path.exists():
            path.unlink()

    return manifest
