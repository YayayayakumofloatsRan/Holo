from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AgentResult:
    task_id: str
    run_id: str
    status: str
    answer: str | None
    stop_reason: str | None
