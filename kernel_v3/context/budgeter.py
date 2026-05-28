from __future__ import annotations

import json
import re

TOKEN_RE = re.compile(r"[A-Za-z0-9]+|[^\w\s]", re.UNICODE)


class BudgetExceeded(ValueError):
    def __init__(self, section_name: str, used: int, limit: int) -> None:
        super().__init__(f"context section {section_name!r} used {used} units over limit {limit}")
        self.section_name = section_name
        self.used = used
        self.limit = limit


def measure_units(payload: object) -> int:
    if payload is None:
        return 0
    try:
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except TypeError:
        encoded = str(payload)
    token_units = len(TOKEN_RE.findall(encoded))
    length_units = max(1, (len(encoded.encode("utf-8")) + 3) // 4)
    return max(token_units, length_units)


def validate_section_budget(section_name: str, payload: object, limit: int) -> int:
    used = measure_units(payload)
    if used > limit:
        raise BudgetExceeded(section_name, used, limit)
    return used
