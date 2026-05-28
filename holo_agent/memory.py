from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .schema import utc_now


@dataclass(slots=True)
class MemoryStore:
    path: Path

    def _read(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"preferences": {}, "notes": [], "updated_at": utc_now()}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return {"preferences": {}, "notes": [], "load_error": "invalid_json", "updated_at": utc_now()}
        return data if isinstance(data, dict) else {"preferences": {}, "notes": [], "updated_at": utc_now()}

    def _write(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = dict(data)
        payload["updated_at"] = utc_now()
        self.path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")

    def snapshot(self) -> dict[str, Any]:
        return self._read()

    def set_preference(self, key: str, value: Any) -> dict[str, Any]:
        data = self._read()
        prefs = dict(data.get("preferences", {}) if isinstance(data.get("preferences", {}), dict) else {})
        prefs[str(key)] = value
        data["preferences"] = prefs
        self._write(data)
        return data

    def add_note(self, text: str, *, kind: str = "note") -> dict[str, Any]:
        data = self._read()
        notes = list(data.get("notes", []) if isinstance(data.get("notes", []), list) else [])
        notes.append({"kind": kind, "text": str(text), "created_at": utc_now()})
        data["notes"] = notes[-200:]
        self._write(data)
        return data

