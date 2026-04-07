from __future__ import annotations

from dataclasses import dataclass

from .config import HostConfig
from .models import IncomingMessage, PolicyDecision

PRESSURE_HINTS = ("压力", "折磨", "退休", "累", "孤独", "焦虑", "anxious", "tired")
URGENT_HINTS = ("紧急", "urgent", "asap", "尽快", "马上")


@dataclass(slots=True)
class AutonomyPolicy:
    config: HostConfig

    def incoming_decision(self, message: IncomingMessage) -> PolicyDecision:
        text = f"{message.subject}\n{message.body_text}".lower()
        priority = 100
        tags: list[str] = []
        if any(hint in text for hint in URGENT_HINTS):
            priority = 130
            tags.append("urgent")
        elif any(hint in text for hint in PRESSURE_HINTS):
            priority = 120
            tags.append("emotional")
        if self._contains_blocked_keyword(text):
            tags.append("high_risk")
        return PolicyDecision(allowed=True, reason="queued", priority=priority, risk_tags=tags)

    def outbound_decision(
        self,
        *,
        incoming_text: str,
        reply_text: str,
        recent_outbound_count: int,
        is_existing_thread: bool,
        is_proactive: bool,
        channel: str = "",
    ) -> PolicyDecision:
        if not reply_text.strip():
            return PolicyDecision(False, "empty_reply", 0, ["empty"])
        limit = self.config.autonomy.max_auto_replies_per_contact_per_hour
        if channel == "wechat" and is_existing_thread:
            # WeChat behaves more like an active back-and-forth chat than email.
            # Keep a generous ceiling here so normal conversation does not stall
            # after a lively exchange or a burst caused by earlier retries.
            limit = max(limit, 120)
        if recent_outbound_count >= limit:
            return PolicyDecision(False, "throttled_contact", 0, ["throttle"])
        haystack = f"{incoming_text}\n{reply_text}".lower()
        if self._contains_blocked_keyword(haystack):
            return PolicyDecision(False, "high_risk_content", 0, ["high_risk"])
        if is_proactive and not is_existing_thread:
            return PolicyDecision(False, "new_contact_proactive_blocked", 0, ["outbound_guard"])
        if self.config.autonomy.auto_send_mode == "draft_only":
            return PolicyDecision(False, "draft_only_mode", 0, ["manual_review"])
        if self.config.autonomy.auto_send_mode == "low_risk_auto" and any(
            hint in haystack for hint in PRESSURE_HINTS
        ):
            return PolicyDecision(False, "manual_for_emotional_turn", 0, ["manual_review"])
        return PolicyDecision(True, "auto_send_allowed", 100, [])

    def should_schedule_proactive(self, thread: dict) -> bool:
        if not self.config.autonomy.allow_proactive_existing_threads:
            return False
        return bool(thread.get("allow_proactive", 1))

    def _contains_blocked_keyword(self, text: str) -> bool:
        lowered = text.lower()
        return any(keyword.lower() in lowered for keyword in self.config.autonomy.blocked_keywords)
