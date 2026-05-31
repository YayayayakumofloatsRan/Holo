from __future__ import annotations

from dataclasses import dataclass, field

from kernel_v3.contracts import JsonObject
from kernel_v3.memory.contracts import MemoryItem
from kernel_v3.privacy import SECRET_KEYS, SECRET_PATTERNS, contains_secret_like_content

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
