from __future__ import annotations

import re
from dataclasses import dataclass, field

from kernel_v3.contracts import JsonObject
from kernel_v3.memory.contracts import MemoryItem


SECRET_PATTERNS = (
    re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----", re.IGNORECASE),
    re.compile(r"\b(?:api[_-]?key|apikey|secret|access[_-]?token|refresh[_-]?token|auth[_-]?token)\b\s*[:=]\s*['\"]?[A-Za-z0-9_\-./+=]{12,}", re.IGNORECASE),
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

REVIEW_PRIVACY_CLASSES = {"user_private", "sensitive"}
ALLOWED_PRIVACY_CLASSES = {"public", "project_internal", "user_private", "sensitive"}


@dataclass(frozen=True, kw_only=True)
class MemoryPrivacyDecision:
    allowed: bool
    approval_required: bool
    risk_flags: list[str]
    reason: str
    redaction: JsonObject = field(default_factory=dict)


def validate_memory_item(item: MemoryItem) -> MemoryPrivacyDecision:
    risk_flags = memory_risk_flags(item.to_dict())
    privacy_class = item.privacy_class
    if privacy_class == "secret_prohibited" or "contains_secret_like_content" in risk_flags:
        return MemoryPrivacyDecision(
            allowed=False,
            approval_required=False,
            risk_flags=risk_flags,
            reason="memory_rejected_secret_like_content",
            redaction={"secrets": "rejected"},
        )
    if privacy_class not in ALLOWED_PRIVACY_CLASSES:
        return MemoryPrivacyDecision(
            allowed=False,
            approval_required=False,
            risk_flags=[*risk_flags, "invalid_privacy_class"],
            reason="invalid_privacy_class",
        )
    approval_required = privacy_class in REVIEW_PRIVACY_CLASSES
    return MemoryPrivacyDecision(
        allowed=True,
        approval_required=approval_required,
        risk_flags=risk_flags,
        reason="allowed_with_review" if approval_required else "allowed",
    )


def memory_risk_flags(value: object) -> list[str]:
    flags: list[str] = []
    if contains_secret_like_content(value):
        flags.append("contains_secret_like_content")
    return flags


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
