from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from typing import TextIO

from kernel_v4.contracts import LoopEvent, now_ms


@dataclass
class WorkflowConsoleMonitor:
    """Render workflow events for real-time human or machine monitoring."""

    mode: str = "compact"
    stream: TextIO = sys.stderr
    started_at_ms: int = field(default_factory=now_ms)
    _text_chars_by_turn: dict[int, int] = field(default_factory=dict)

    def __call__(self, event: LoopEvent) -> None:
        if self.mode == "jsonl":
            self._emit_jsonl(event)
            return
        line = self._compact_line(event)
        if line:
            print(line, file=self.stream, flush=True)

    def _emit_jsonl(self, event: LoopEvent) -> None:
        print(
            json.dumps(
                {
                    "workflow_event": event.event_type,
                    "turn_index": event.turn_index,
                    "at_ms": event.at_ms,
                    "elapsed_ms": max(0, event.at_ms - self.started_at_ms),
                    "data": event.data,
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            file=self.stream,
            flush=True,
        )

    def _compact_line(self, event: LoopEvent) -> str | None:
        event_type = event.event_type
        turn = event.turn_index
        elapsed = _format_elapsed(max(0, event.at_ms - self.started_at_ms))
        data = event.data

        if event_type == "assistant_text_delta":
            self._text_chars_by_turn[turn] = self._text_chars_by_turn.get(turn, 0) + int(data.get("chars") or 0)
            return None
        if event_type == "loop_start":
            return f"{elapsed} t{turn} loop_start run={data.get('run_id')} thread={data.get('thread_key')}"
        if event_type == "model_turn_start":
            return (
                f"{elapsed} t{turn} model_start messages={data.get('message_count')} "
                f"tools={data.get('visible_tool_count')}"
            )
        if event_type == "assistant_tool_call":
            return f"{elapsed} t{turn} assistant_tool_call tool={data.get('tool')} call={_short_call(data.get('tool_call_id'))}"
        if event_type == "tool_queued":
            return f"{elapsed} t{turn} tool_queued tool={data.get('tool')} call={_short_call(data.get('tool_call_id'))}"
        if event_type == "tool_start":
            return f"{elapsed} t{turn} tool_start tool={data.get('tool')} call={_short_call(data.get('tool_call_id'))}"
        if event_type == "tool_result":
            status = "error" if data.get("is_error") else "ok"
            artifact = f" artifact={data.get('artifact_id')}" if data.get("artifact_id") else ""
            return f"{elapsed} t{turn} tool_result {status} tool={data.get('tool')} call={_short_call(data.get('tool_call_id'))}{artifact}"
        if event_type == "tool_cancelled":
            return (
                f"{elapsed} t{turn} tool_cancelled tool={data.get('tool')} "
                f"call={_short_call(data.get('tool_call_id'))} reason={data.get('reason')}"
            )
        if event_type == "assistant_message_stop":
            chars = self._text_chars_by_turn.pop(turn, 0)
            return f"{elapsed} t{turn} assistant_stop text_chars={chars}"
        if event_type == "loop_completed":
            return f"{elapsed} t{turn} loop_completed answer_chars={data.get('answer_chars')}"
        if event_type == "loop_failed":
            return f"{elapsed} t{turn} loop_failed reason={data.get('reason')}"
        if event_type == "loop_aborted":
            return f"{elapsed} t{turn} loop_aborted reason={data.get('reason')}"
        if event_type == "tool_budget_exceeded":
            return f"{elapsed} t{turn} tool_budget_exceeded tool={data.get('tool')} max_new={data.get('max_new_tool_calls')}"
        return None


def _format_elapsed(elapsed_ms: int) -> str:
    return f"{elapsed_ms / 1000:8.2f}s"


def _short_call(value: object) -> str:
    text = str(value or "")
    if len(text) <= 18:
        return text
    return text[:8] + ".." + text[-6:]
