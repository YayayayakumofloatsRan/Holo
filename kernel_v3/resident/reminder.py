from __future__ import annotations

import re
from dataclasses import dataclass, field

from kernel_v3.contracts import Contract, JsonObject


_ZH_NUMBERS = {
    "零": 0,
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
}
_UNIT_MS = {
    "秒": 1_000,
    "second": 1_000,
    "seconds": 1_000,
    "分": 60_000,
    "分钟": 60_000,
    "minute": 60_000,
    "minutes": 60_000,
    "小时": 3_600_000,
    "时": 3_600_000,
    "hour": 3_600_000,
    "hours": 3_600_000,
    "天": 86_400_000,
    "day": 86_400_000,
    "days": 86_400_000,
}
_RELATIVE_REMINDER_PATTERNS = (
    re.compile(
        r"(?P<amount>\d+|[零一二两三四五六七八九十]{1,3})\s*(?P<unit>秒|分钟|分|小时|时|天)\s*(?:后|以后|之后).{0,24}?(?:提醒我|提醒|叫我|通知我)(?P<body>.*)",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:remind\s+me|notify\s+me|alert\s+me)\s+(?:in|after)\s+(?P<amount>\d+)\s+(?P<unit>seconds?|minutes?|hours?|days?)(?P<body>.*)",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:in|after)\s+(?P<amount>\d+)\s+(?P<unit>seconds?|minutes?|hours?|days?).{0,24}?(?:remind\s+me|notify\s+me|alert\s+me)(?P<body>.*)",
        re.IGNORECASE,
    ),
)


@dataclass(frozen=True, kw_only=True)
class ReminderDirective(Contract):
    reminder_text: str
    due_in_ms: int
    priority: int = 0
    interval_ms: int | None = None
    max_runs: int | None = 1
    metadata: JsonObject = field(default_factory=dict)


def compile_reminder(text: str, *, default_priority: int = 0) -> ReminderDirective | None:
    normalized = " ".join(str(text or "").strip().split())
    if not normalized:
        return None
    for pattern in _RELATIVE_REMINDER_PATTERNS:
        match = pattern.search(normalized)
        if match is None:
            continue
        due_in_ms = _duration_ms(match.group("amount"), match.group("unit"))
        if due_in_ms is None:
            continue
        reminder_text = _reminder_text(normalized, match.groupdict().get("body"))
        return ReminderDirective(
            reminder_text=reminder_text,
            due_in_ms=due_in_ms,
            priority=_priority_for_delay(due_in_ms, default_priority=default_priority),
            metadata={
                "compiler": "relative_reminder_v1",
                "source_text_preview": normalized[:160],
                "duration_ms": due_in_ms,
            },
        )
    return None


def _duration_ms(amount: str, unit: str) -> int | None:
    value = _parse_amount(amount)
    multiplier = _UNIT_MS.get(str(unit).lower())
    if value <= 0 or multiplier is None:
        return None
    return value * multiplier


def _parse_amount(value: str) -> int:
    if str(value).isdigit():
        return int(value)
    text = str(value)
    if text in _ZH_NUMBERS:
        return _ZH_NUMBERS[text]
    if text.startswith("十"):
        tail = text[1:]
        return 10 + _ZH_NUMBERS.get(tail, 0)
    if "十" in text:
        head, _, tail = text.partition("十")
        return _ZH_NUMBERS.get(head, 0) * 10 + _ZH_NUMBERS.get(tail, 0)
    return 0


def _reminder_text(source_text: str, body: str | None) -> str:
    cleaned = str(body or "").strip()
    cleaned = re.sub(r"^(?:我|to|that|about|做|去|：|:|,|，|\s)+", "", cleaned, flags=re.IGNORECASE).strip()
    if cleaned:
        return f"提醒：{cleaned}"
    return f"提醒：{source_text}"


def _priority_for_delay(delay_ms: int, *, default_priority: int) -> int:
    if delay_ms <= 10 * 60_000:
        return max(default_priority, 20)
    if delay_ms <= 60 * 60_000:
        return max(default_priority, 10)
    return default_priority
