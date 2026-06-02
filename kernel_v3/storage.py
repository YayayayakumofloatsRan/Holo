from __future__ import annotations

import os
import re
from pathlib import Path


HOLO_STATE_DIR_ENV = "HOLO_V3_STATE_DIR"
DEFAULT_STATE_ROOT = Path(".state/kernel_v3")


def state_root() -> Path:
    configured = os.environ.get(HOLO_STATE_DIR_ENV)
    if configured:
        return Path(configured)
    return DEFAULT_STATE_ROOT


def default_journal_path() -> Path:
    return state_root() / "journal" / "global.jsonl"


def default_journal_index_path() -> Path:
    return state_root() / "journal" / "global.sqlite"


def default_thread_root() -> Path:
    return state_root() / "threads"


def default_memory_log_path() -> Path:
    return state_root() / "memory" / "memory.jsonl"


def default_memory_index_path() -> Path:
    return state_root() / "memory" / "memory.sqlite"


def safe_storage_id(value: str) -> str:
    text = str(value or "default").strip() or "default"
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", text).strip("._-")
    return cleaned or "default"
