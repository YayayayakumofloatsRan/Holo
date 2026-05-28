import json

from kernel_v3.context import ContextPackCompiler
from kernel_v3.journal import JournalStore
from kernel_v3.session import SessionEngine
from kernel_v3.trace import TraceRenderer


def test_context_pack_is_sectioned_bounded_hash_stable_and_roundtrips():
    journal = JournalStore.in_memory()
    task = SessionEngine.from_journal(journal).start("inspect README", thread_id="thread-a", journal=journal)
    event = journal.append(
        task_id=task.task_id,
        run_id=task.run_id,
        step_id=task.step_id,
        kind="event",
        data={"event_id": "evt-1", "text": "inspect README"},
        event_ref="evt-1",
    )
    observation = journal.append(
        task_id=task.task_id,
        run_id=task.run_id,
        step_id="step-1",
        kind="observation",
        data={"observation_id": "obs-1", "content": "README says Holo is local."},
        event_ref="evt-1",
        observation_ref="obs-1",
    )

    compiler = ContextPackCompiler(token_budget=128, permission_state={"mode": "read_only"})
    pack = compiler.compile(task, journal, tool_briefs=[{"name": "file.read", "side_effect": "read"}])
    same_pack = compiler.compile(task, journal, tool_briefs=[{"name": "file.read", "side_effect": "read"}])

    assert [section["name"] for section in pack.sections] == [
        "user_event",
        "active_task_state",
        "recent_observations",
        "tool_briefs",
        "permission_state",
        "memory_refs",
    ]
    assert pack.source_refs == [event.record_id, observation.record_id]
    assert pack.budget == {"token_budget": 128, "section_count": 6}
    assert pack.redactions == []
    assert pack.payload_hash == same_pack.payload_hash
    assert ContextPackCompiler.from_dict(json.loads(json.dumps(pack.to_dict()))) == pack


def test_trace_renderer_uses_journal_only():
    journal = JournalStore.in_memory()
    journal.append(
        task_id="task-1",
        run_id="run-1",
        step_id="step-0",
        kind="event",
        data={"event_id": "evt-1", "text": "hello"},
        event_ref="evt-1",
        state_delta={"status": "event_received"},
    )
    journal.append(
        task_id="task-1",
        run_id="run-1",
        step_id="step-1",
        kind="observation",
        data={"observation_id": "obs-1", "status": "ok"},
        event_ref="evt-1",
        observation_ref="obs-1",
        state_delta={"status": "observed"},
    )

    trace = TraceRenderer(journal).render_task("task-1")

    assert "Trace task-1" in trace
    assert "run-1 step-0 event event=evt-1" in trace
    assert "run-1 step-1 observation event=evt-1 observation=obs-1" in trace
    assert "state_delta={'status': 'observed'}" in trace
