from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from kernel_v3.privacy import contains_secret_like_content


SECRET_KEY_RE = re.compile(r"(api[_-]?key|token|secret|password)", re.IGNORECASE)
SECRET_VALUE_RE = re.compile(r"(?<![A-Za-z0-9_-])(sk-[A-Za-z0-9_-]{8,}|token=[A-Za-z0-9_-]{6,})")
SAFE_SECRET_KEYS = {"token_budget"}


@dataclass
class Redactor:
    private_path_markers: list[str] = field(default_factory=list)

    def redact(self, payload: Any) -> tuple[Any, list[str]]:
        markers: set[str] = set()
        return self._redact_value(payload, markers), sorted(markers)

    def _redact_value(self, payload: Any, markers: set[str]) -> Any:
        if isinstance(payload, dict):
            redacted: dict[str, Any] = {}
            for key, value in payload.items():
                if str(key) not in SAFE_SECRET_KEYS and SECRET_KEY_RE.search(str(key)) and self._looks_secretish(value):
                    markers.add("SECRET")
                    redacted[key] = "[REDACTED:SECRET]"
                else:
                    redacted[key] = self._redact_value(value, markers)
            return redacted
        if isinstance(payload, list):
            return [self._redact_value(item, markers) for item in payload]
        if isinstance(payload, str):
            text = payload
            for marker in self.private_path_markers:
                if marker and marker in text:
                    markers.add("PRIVATE_PATH")
                    text = text.replace(marker, "[REDACTED:PRIVATE_PATH]")
            if SECRET_VALUE_RE.search(text):
                markers.add("SECRET")
                text = SECRET_VALUE_RE.sub("[REDACTED:SECRET]", text)
            if contains_secret_like_content(text):
                markers.add("SECRET")
                text = "[REDACTED:SECRET]"
            return text
        return payload

    @staticmethod
    def _looks_secretish(value: Any) -> bool:
        if value is None:
            return False
        if isinstance(value, bool):
            return False
        if isinstance(value, (int, float)):
            return False
        if isinstance(value, str):
            return bool(value and len(value) > 16)
        return True
