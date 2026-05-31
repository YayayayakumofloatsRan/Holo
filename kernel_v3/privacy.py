from __future__ import annotations

import re


SECRET_PATTERNS = (
    re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----", re.IGNORECASE),
    re.compile(
        r"\b(?:api[_-]?key|apikey|secret|access[_-]?token|refresh[_-]?token|auth[_-]?token)\b\s*[:=]\s*['\"]?[A-Za-z0-9_\-./+=]{12,}",
        re.IGNORECASE,
    ),
    re.compile(r"\bBearer\s+[A-Za-z0-9_\-./+=]{12,}", re.IGNORECASE),
    re.compile(r"\b(?:sk|rk|pk|ghp|github_pat)_[A-Za-z0-9_\-]{12,}\b", re.IGNORECASE),
    re.compile(r"\b[A-Za-z0-9_\-]{20,}\.[A-Za-z0-9_\-]{20,}\.[A-Za-z0-9_\-]{20,}\b"),
)

SECRET_KEYS = {
    "api_key",
    "apikey",
    "secret",
    "token",
    "access_token",
    "refresh_token",
    "authorization",
    "cookie",
    "private_key",
}


def contains_secret_like_content(value: object) -> bool:
    if isinstance(value, str):
        return any(pattern.search(value) for pattern in SECRET_PATTERNS)
    if isinstance(value, dict):
        for key, item in value.items():
            if str(key).lower() in SECRET_KEYS and _looks_secret_value(item):
                return True
            if contains_secret_like_content(item):
                return True
        return False
    if isinstance(value, list):
        return any(contains_secret_like_content(item) for item in value)
    return False


def _looks_secret_value(value: object) -> bool:
    if not isinstance(value, str):
        return value not in (None, "", [])
    stripped = value.strip()
    if len(stripped) >= 8:
        return True
    return any(pattern.search(stripped) for pattern in SECRET_PATTERNS)
