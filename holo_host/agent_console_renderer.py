from __future__ import annotations

from typing import Any

from .agent_event_stream import render_agent_event_stream
from .common import stable_digest, utc_now
from .public_thought_stream import render_public_thought_stream

STAGE207_AGENT_CONSOLE_SCHEMA = "holo.stage207.agent_console.v1"

_ANSI_FAINT = "\x1b[2m"
_ANSI_RESET = "\x1b[0m"


def _lines(value: str) -> list[str]:
    return [line for line in str(value or "").splitlines() if line.strip()]


def _faint(line: str, *, use_ansi: bool) -> str:
    current = str(line or "")
    if not use_ansi:
        return current
    return f"{_ANSI_FAINT}{current}{_ANSI_RESET}"


def _final_from_text(final_text: str, event_stream: dict[str, Any] | None) -> str:
    current = str(final_text or "").strip()
    if current:
        return current
    stream = event_stream if isinstance(event_stream, dict) else {}
    for item in reversed(list(stream.get("events", []) or [])):
        if isinstance(item, dict) and str(item.get("event", "") or "") == "final":
            return str(item.get("summary", "") or "").strip()
    return ""


def _render_system_lines(
    *,
    event_stream: dict[str, Any] | None,
    public_thought_stream: dict[str, Any] | None,
) -> list[str]:
    rendered_trace = render_agent_event_stream(event_stream)
    trace_lines = [line for line in _lines(rendered_trace) if not line.startswith("[final]")]
    rendered_thoughts = render_public_thought_stream(public_thought_stream)
    thought_lines = _lines(rendered_thoughts)
    # Trace comes first because it is the external audit trail. Thought cards are
    # derived summaries over the same public events, not hidden reasoning.
    return trace_lines + thought_lines


def build_agent_console_report(
    *,
    user_text: str = "",
    final_text: str = "",
    event_stream: dict[str, Any] | None = None,
    public_thought_stream: dict[str, Any] | None = None,
) -> dict[str, Any]:
    system_lines = _render_system_lines(event_stream=event_stream, public_thought_stream=public_thought_stream)
    final = _final_from_text(final_text, event_stream)
    return {
        "schema": STAGE207_AGENT_CONSOLE_SCHEMA,
        "console_id": "stage207_console:" + stable_digest(user_text, final, str(len(system_lines)), limit=12),
        "user_text_present": bool(str(user_text or "").strip()),
        "system_line_count": len(system_lines),
        "final_text_present": bool(final),
        "uses_public_thought_stream": bool(
            isinstance(public_thought_stream, dict) and list(public_thought_stream.get("cards", []) or [])
        ),
        "hidden_reasoning_exposed": False,
        "created_at": utc_now(),
    }


def render_agent_console_turn(
    *,
    user_text: str = "",
    final_text: str = "",
    event_stream: dict[str, Any] | None = None,
    public_thought_stream: dict[str, Any] | None = None,
    use_ansi: bool = False,
) -> str:
    user = str(user_text or "").strip()
    final = _final_from_text(final_text, event_stream)
    output: list[str] = []
    if user:
        output.append(f"holo> {user}")
    for line in _render_system_lines(event_stream=event_stream, public_thought_stream=public_thought_stream):
        output.append(_faint(line, use_ansi=use_ansi))
    if final:
        output.append(final)
    return "\n".join(output)
