from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from .common import compact_text, utc_now


INNER_STREAM_NAME = "inner_stream"
INNER_STREAM_PHASES = (
    "sensory_edge",
    "attention_focus",
    "affective_tension",
    "memory_echo",
    "goal_pressure",
    "inhibition_gate",
    "candidate_action",
)


def _as_list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _compact(value: Any, limit: int = 160) -> str:
    return compact_text(str(value or "").strip(), limit)


def _as_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _json_dict(text: str) -> dict[str, Any]:
    current = str(text or "").strip()
    if not current:
        return {}
    try:
        loaded = json.loads(current)
    except json.JSONDecodeError:
        return {}
    return dict(loaded) if isinstance(loaded, dict) else {}


def _latest_loop_signal(brain_status: dict[str, Any]) -> tuple[str, str]:
    loops = [dict(item) for item in _as_list(brain_status.get("loops")) if isinstance(item, dict)]
    active = [item for item in loops if str(item.get("status", "") or "").strip() not in {"", "never", "idle"}]
    source = active[0] if active else (loops[0] if loops else {})
    loop_name = _compact(source.get("loop_name"), 60)
    summary = _compact(
        source.get("influence_summary")
        or source.get("blocked_reason")
        or source.get("status")
        or "baseline cortical noise",
        180,
    )
    return loop_name or "baseline", summary


@dataclass(slots=True)
class InnerStreamRuntime:
    """Volatile runtime buffer for endogenous subject-state micro-ticks."""

    max_ticks: int = 64
    _sequence: int = 0
    _ticks: list[dict[str, Any]] = field(default_factory=list)

    def tick(
        self,
        *,
        mode: str,
        idle_seconds: float,
        latest_activity_at: str,
        brain_status: dict[str, Any],
        processor_result: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self._sequence += 1
        loop_name, loop_signal = _latest_loop_signal(brain_status)
        processor = _as_dict(processor_result)
        processor_metadata = _as_dict(processor.get("metadata"))
        processor_text = _compact(processor.get("text"), 600)
        processor_payload = _json_dict(processor_text)
        processor_status = _compact(processor.get("status") or ("ok" if int(processor.get("returncode", 0) or 0) == 0 else "error"), 40)
        processor_invoked = bool(processor)
        has_activity = bool(str(latest_activity_at or "").strip())
        idle = max(0.0, float(idle_seconds or 0.0)) if has_activity else 0.0
        sensory_edge = (
            f"idle:{round(idle, 2)}s since {latest_activity_at}"
            if has_activity
            else "no external activity recorded; endogenous baseline tick"
        )
        attention_focus = _compact(processor_payload.get("attention_focus"), 180) or f"{loop_name}:{loop_signal}"
        affective_tension = round(min(1.0, 0.08 + idle / 3600.0), 4)
        memory_echo = _compact(processor_payload.get("memory_echo"), 180) or (
            loop_signal if loop_signal != "baseline cortical noise" else "no salient recall yet"
        )
        goal_pressure = _compact(processor_payload.get("goal_pressure"), 140) or (
            "preserve_continuity" if mode in {"companion", "full_brain"} else "maintain_runtime_integrity"
        )
        inhibition_gate = _compact(processor_payload.get("inhibition_gate"), 160) or "volatile_only:no_transport:no_policy:no_self_memory"
        candidate_action = _compact(processor_payload.get("candidate_action"), 120) or "continue_inner_flow"
        micro_thought = (
            _compact(processor_payload.get("micro_thought"), 220)
            or _compact(processor_payload.get("summary"), 220)
            or _compact(processor_text, 220)
            or "local baseline tick"
        )

        tick = {
            "stream_name": INNER_STREAM_NAME,
            "status": "flowing" if processor_status in {"", "ok"} else "error",
            "blocked_reason": ""
            if processor_status in {"", "ok"}
            else _compact(processor.get("stderr") or processor.get("error") or processor_status, 180),
            "sequence": self._sequence,
            "created_at": utc_now(),
            "mode": str(mode or ""),
            "phase_order": list(INNER_STREAM_PHASES),
            "processor_invoked": processor_invoked,
            "micro_thought": micro_thought,
            "sensory_edge": sensory_edge,
            "attention_focus": attention_focus,
            "affective_tension": affective_tension,
            "memory_echo": memory_echo,
            "goal_pressure": goal_pressure,
            "inhibition_gate": inhibition_gate,
            "candidate_action": candidate_action,
            "authority": {
                "memory_write": "volatile_ring_only",
                "self_memory_write": False,
                "policy_write": False,
                "transport_write": False,
                "model_call": processor_invoked,
            },
            "processor": {
                "status": processor_status or "skipped",
                "provider": _compact(processor_metadata.get("provider"), 80),
                "model": _compact(processor_metadata.get("model"), 120),
                "lane": _compact(processor_metadata.get("lane"), 80),
                "returncode": int(processor.get("returncode", 0) or 0),
            },
            "motifs": [loop_name, goal_pressure],
        }
        self._ticks.append(tick)
        if len(self._ticks) > max(1, int(self.max_ticks or 1)):
            del self._ticks[: len(self._ticks) - max(1, int(self.max_ticks or 1))]
        return dict(tick)

    def state(self) -> dict[str, Any]:
        latest = dict(self._ticks[-1]) if self._ticks else {}
        return {
            "stream_name": INNER_STREAM_NAME,
            "sequence": self._sequence,
            "phase_order": list(INNER_STREAM_PHASES),
            "latest_tick": latest,
            "recent_ticks": [dict(item) for item in self._ticks],
            "authority": {
                "memory_write": "volatile_ring_only",
                "self_memory_write": False,
                "policy_write": False,
                "transport_write": False,
                "model_call": bool(latest.get("processor_invoked", False)),
            },
        }
