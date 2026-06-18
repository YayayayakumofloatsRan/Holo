from __future__ import annotations

from io import StringIO

from kernel_v4.contracts import LoopEvent
from kernel_v4.monitoring import WorkflowConsoleMonitor


def test_workflow_console_monitor_compact_coalesces_text_deltas() -> None:
    stream = StringIO()
    monitor = WorkflowConsoleMonitor(mode="compact", stream=stream)

    monitor(LoopEvent(event_type="model_turn_start", turn_index=1, data={"message_count": 1, "visible_tool_count": 3}))
    monitor(LoopEvent(event_type="assistant_text_delta", turn_index=1, data={"chars": 5}))
    monitor(LoopEvent(event_type="assistant_text_delta", turn_index=1, data={"chars": 7}))
    monitor(LoopEvent(event_type="tool_start", turn_index=1, data={"tool_call_id": "call-1234567890", "tool": "calculator.compute"}))
    monitor(LoopEvent(event_type="assistant_message_stop", turn_index=1, data={}))

    output = stream.getvalue()

    assert "model_start messages=1 tools=3" in output
    assert "tool_start tool=calculator.compute" in output
    assert "assistant_stop text_chars=12" in output
    assert "assistant_text_delta" not in output


def test_workflow_console_monitor_jsonl_preserves_machine_events() -> None:
    stream = StringIO()
    monitor = WorkflowConsoleMonitor(mode="jsonl", stream=stream)

    monitor(LoopEvent(event_type="loop_completed", turn_index=2, data={"answer_chars": 42}))

    output = stream.getvalue()

    assert '"workflow_event": "loop_completed"' in output
    assert '"answer_chars": 42' in output
