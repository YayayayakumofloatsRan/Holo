import json
import subprocess
import sys
from pathlib import Path

from kernel_v3.context import ContextCompiler
from kernel_v3.contracts import CandidateAction, Observation
from kernel_v3.journal import JournalStore
from kernel_v3.loop import LoopControllerV3
from kernel_v3.policy import PolicyGate
from kernel_v3.testing.fakes import FakeEvaluator, FakePlanner
from kernel_v3.tools import ToolRegistry


def test_loop_journals_step_ids_for_each_iteration():
    search = CandidateAction(
        action_id="act-search",
        kind="tool",
        name="workspace.search",
        description="search",
        score=1.0,
        payload={"query": "Holo"},
        reasons=[],
        side_effect_class="read",
    )
    read = CandidateAction(
        action_id="act-read",
        kind="tool",
        name="file.read",
        description="read",
        score=1.0,
        payload={"path": "README.md"},
        reasons=[],
        side_effect_class="read",
    )
    registry = ToolRegistry()
    registry.register("workspace.search", _ok_tool)
    registry.register("file.read", _ok_tool)
    journal = JournalStore.in_memory()
    loop = LoopControllerV3(
        journal=journal,
        context_compiler=ContextCompiler(),
        planner=FakePlanner([search, read]),
        policy_gate=PolicyGate(permission="read_write"),
        tool_registry=registry,
        evaluator=FakeEvaluator(
            [
                {"status": "continue", "missing_evidence": ["need file.read"], "answer": None},
                {"status": "final_answer_ready", "missing_evidence": [], "answer": "done"},
            ]
        ),
    )

    result = loop.run("inspect README")

    step_records = [
        record
        for record in journal.records(task_id=result.task_id)
        if record.kind in {"context", "action", "policy_decision", "observation", "feedback"}
    ]
    assert [record.step_id for record in step_records[:5]] == ["step-1"] * 5
    assert [record.step_id for record in step_records[5:]] == ["step-2"] * 5
    assert journal.records(task_id=result.task_id, kind="result")[0].step_id == "step-2"


def test_journal_sqlite_index_is_queryable():
    journal_path = Path("kernel_v3/.test-phase1-index-query.jsonl")
    index_path = Path("kernel_v3/.test-phase1-index-query.sqlite")
    _unlink(journal_path, index_path)
    try:
        store = JournalStore(journal_path=journal_path, index_path=index_path)
        event = store.append(
            task_id="task-1",
            run_id="run-1",
            step_id="step-0",
            kind="event",
            data={"event_id": "evt-1"},
            event_ref="evt-1",
        )
        observation = store.append(
            task_id="task-1",
            run_id="run-1",
            step_id="step-1",
            kind="observation",
            data={"observation_id": "obs-1"},
            event_ref="evt-1",
            observation_ref="obs-1",
        )

        rows = store.index_records(task_id="task-1", kind="observation")

        assert [row["record_id"] for row in rows] == [observation.record_id]
        assert rows[0]["record_id"] != event.record_id
        assert rows[0]["payload_hash"] == observation.payload_hash
    finally:
        _unlink(journal_path, index_path)


def test_holo_v3_launcher_surfaces_dev_console():
    journal_path = Path("kernel_v3/.test-phase1-launcher.jsonl")
    index_path = Path("kernel_v3/.test-phase1-launcher.sqlite")
    _unlink(journal_path, index_path)
    try:
        result = subprocess.run(
            [
                sys.executable,
                "holo-v3",
                "--journal",
                str(journal_path),
                "--index",
                str(index_path),
                "run",
                "hello",
            ],
            cwd=Path(__file__).resolve().parents[1],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )

        payload = json.loads(result.stdout)
        assert payload["status"] == "completed"
        assert payload["task_id"] == "task-1"
    finally:
        _unlink(journal_path, index_path)


def _ok_tool(action: CandidateAction) -> Observation:
    return Observation(
        observation_id=f"obs-{action.action_id}",
        run_id="",
        kind="tool_result",
        status="ok",
        source=f"tool:{action.name}",
        content={"ok": True},
        observed_at_ms=0,
        action_id=action.action_id,
        tool_call_id=None,
    )


def _unlink(*paths: Path) -> None:
    for path in paths:
        if path.exists():
            path.unlink()
