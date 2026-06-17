from __future__ import annotations

from collections.abc import Iterable

from kernel_v3.journal import JournalStore
from kernel_v3.contracts import ProcessorRequest, ProcessorResult
from kernel_v3.processors.contracts import ProcessorStreamEvent
from kernel_v3.processors.fabric import ProcessorFabric


class StreamingProvider:
    name = "streaming"
    model = "stream-model"

    def run(self, request: ProcessorRequest) -> ProcessorResult:
        raise AssertionError("streaming provider should not use run()")

    def stream(self, request: ProcessorRequest) -> Iterable[ProcessorStreamEvent]:
        yield ProcessorStreamEvent(
            event_type="stream_start",
            request_id=request.request_id,
            sequence=1,
            delta={"provider": self.name},
        )
        yield ProcessorStreamEvent(
            event_type="tool_call_delta",
            request_id=request.request_id,
            sequence=2,
            delta={"tool_calls": [{"id": "tc-1", "function": {"name": "workspace.search", "arguments": "{}"}}]},
        )
        yield ProcessorStreamEvent(
            event_type="stream_end",
            request_id=request.request_id,
            sequence=3,
            delta={"status": "ok"},
        )


class NonStreamingProvider:
    name = "nonstream"
    model = "nonstream-model"

    def run(self, request: ProcessorRequest) -> ProcessorResult:
        return ProcessorResult(
            result_id=f"result-{request.request_id}",
            request_id=request.request_id,
            status="ok",
            output={"text": '{"ok": true}'},
            usage={},
            error=None,
        )


def test_processor_fabric_delegates_streaming_provider_events() -> None:
    fabric = ProcessorFabric(providers={"streaming": StreamingProvider()})

    events = fabric.stream_events(
        task_type="assistant.turn",
        run_id="run-1",
        context_id="ctx-1",
        prompt="call a tool",
        provider="streaming",
        model="stream-model",
    )

    assert [event.event_type for event in events] == ["stream_start", "tool_call_delta", "stream_end"]
    assert events[1].delta["tool_calls"][0]["function"]["name"] == "workspace.search"
    assert events[0].to_dict()["schema"] == "holo.kernel_v3.processor_stream_event.v1"


def test_processor_fabric_falls_back_to_non_streaming_run() -> None:
    fabric = ProcessorFabric(providers={"nonstream": NonStreamingProvider()})

    events = fabric.stream_events(
        task_type="assistant.turn",
        run_id="run-1",
        context_id="ctx-1",
        prompt="answer",
        provider="nonstream",
        model="nonstream-model",
    )

    assert [event.event_type for event in events] == ["stream_start", "content_delta", "stream_end"]
    assert events[1].delta["text"] == '{"ok": true}'
    assert events[2].delta["status"] == "ok"


def test_processor_fabric_iter_stream_events_yields_incrementally_and_journals() -> None:
    seen: list[str] = []
    journal = JournalStore.in_memory()
    fabric = ProcessorFabric(providers={"incremental": IncrementalStreamingProvider(seen)}, journal=journal)

    iterator = fabric.iter_stream_events(
        task_type="assistant.turn",
        task_id="task-1",
        run_id="run-1",
        context_id="ctx-1",
        prompt="call a tool",
        provider="incremental",
        model="stream-model",
    )

    first = next(iterator)

    assert first.event_type == "stream_start"
    assert seen == ["start"]
    assert [event.event_type for event in iterator] == ["content_delta", "stream_end"]
    stream_records = journal.records(task_id="task-1", kind="processor_stream")
    assert stream_records[0].data["event_count"] == 3


class IncrementalStreamingProvider:
    name = "incremental"
    model = "stream-model"

    def __init__(self, seen: list[str]) -> None:
        self.seen = seen

    def run(self, request: ProcessorRequest) -> ProcessorResult:
        raise AssertionError("incremental provider should not use run()")

    def stream(self, request: ProcessorRequest) -> Iterable[ProcessorStreamEvent]:
        self.seen.append("start")
        yield ProcessorStreamEvent(
            event_type="stream_start",
            request_id=request.request_id,
            sequence=1,
            delta={},
        )
        self.seen.append("content")
        yield ProcessorStreamEvent(
            event_type="content_delta",
            request_id=request.request_id,
            sequence=2,
            delta={"text": "hello"},
        )
        self.seen.append("end")
        yield ProcessorStreamEvent(
            event_type="stream_end",
            request_id=request.request_id,
            sequence=3,
            delta={"status": "ok"},
        )
