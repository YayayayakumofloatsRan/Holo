from __future__ import annotations

import subprocess
import sys
from pathlib import PurePosixPath


FORBIDDEN_EXACT = {
    ".subject.local.md",
    "holo_memory_library/subject_seed.md",
    "holo_memory_library/voice_profile.md",
    "windows_helper/wechat_helper.live.json",
}

FORBIDDEN_PREFIXES = (
    ".holo_runtime/",
    "artifacts/",
)

FORBIDDEN_MEMORY_SUFFIXES = (
    ".jsonl",
    ".sqlite",
    ".sqlite3",
    ".db",
)

FORBIDDEN_TEXT_MARKERS = tuple(
    "".join(parts)
    for parts in (
        ("Nem", "oqi"),
        ("Ran", " Yakumo"),
        ("ran", "_yakumo"),
        ("\u54b1",),
        ("\u8d6b", "\u841d"),
        ("\u72fc", "\u4e0e", "\u9999", "\u8f9b", "\u6599"),
        ("\u8d24", "\u72fc"),
        ("\u8001", "\u72fc"),
    )
)

TEXT_SCAN_SKIP_SUFFIXES = (
    ".png",
    ".gif",
    ".jpg",
    ".jpeg",
    ".exe",
    ".docx",
    ".sqlite",
    ".sqlite3",
    ".db",
)


def _tracked_files() -> list[str]:
    result = subprocess.run(
        ["git", "ls-files"],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return [line.strip().replace("\\", "/") for line in result.stdout.splitlines() if line.strip()]


def _read_text(path: str) -> str | None:
    if path.endswith(TEXT_SCAN_SKIP_SUFFIXES):
        return None
    try:
        data = PurePosixPath(path)
        with open(data, "rb") as handle:
            raw = handle.read()
    except OSError:
        return None
    if b"\x00" in raw:
        return None
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return None


def _is_forbidden(path: str) -> bool:
    if path in FORBIDDEN_EXACT:
        return True
    if any(path.startswith(prefix) for prefix in FORBIDDEN_PREFIXES):
        return True
    if path.startswith("holo_memory_library/memories/") and path != "holo_memory_library/memories/README.md":
        return True
    name = PurePosixPath(path).name
    if path.startswith("holo_memory_library/memories/") and name.endswith(FORBIDDEN_MEMORY_SUFFIXES):
        return True
    return False


def main() -> int:
    tracked = _tracked_files()
    forbidden = [path for path in tracked if _is_forbidden(path)]
    marker_hits: list[str] = []
    for path in tracked:
        text = _read_text(path)
        if text is None:
            continue
        for marker in FORBIDDEN_TEXT_MARKERS:
            if marker in text:
                marker_hits.append(path)
                break
    if forbidden or marker_hits:
        print("Public release hygiene failed. Forbidden tracked paths:")
        for path in forbidden:
            print(f"- {path}")
        if marker_hits:
            print("Forbidden private/persona markers found in tracked text:")
            for path in sorted(set(marker_hits)):
                print(f"- {path}")
        return 1
    print("Public release hygiene passed: no private profile, memory, runtime, artifact, live transport path, or blocked persona marker is tracked.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
