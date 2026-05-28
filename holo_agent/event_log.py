from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .schema import Event

PRIVATE_KEYS = {"reasoning_content", "chain_of_thought", "hidden_reasoning", "internal_messages"}


def sanitize(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): sanitize(v) for k, v in value.items() if str(k) not in PRIVATE_KEYS}
    if isinstance(value, list):
        return [sanitize(item) for item in value]
    if isinstance(value, str) and any(key in value.lower() for key in PRIVATE_KEYS):
        return "[redacted]"
    return value


class EventLog:
    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, event: Event) -> None:
        payload = sanitize(event.to_dict())
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")

    def read(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        rows: list[dict[str, Any]] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            rows.append(json.loads(line))
        return rows

