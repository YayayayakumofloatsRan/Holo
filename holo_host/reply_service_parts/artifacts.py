from __future__ import annotations

from pathlib import Path


def normalize_artifact_dir(path: str | None) -> str | None:
    text = str(path or "").strip()
    if not text:
        return None
    return str(Path(text))
