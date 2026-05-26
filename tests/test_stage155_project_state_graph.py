from __future__ import annotations

import tempfile
from pathlib import Path

from holo_host.config import load_config
from holo_host.models import IncomingMessage
from holo_host.project_state_graph import (
    PROJECT_STATE_GRAPH_SCHEMA,
    ProjectStateGraph,
    detect_project_state_updates,
)
from holo_host.reply_api import HoloReplyService
from holo_host.stage135_i_state_topology import build_stage135_i_state_topology
from holo_host.stage150_context_memory_fabric import build_stage150_context_memory_fabric, stage150_prompt_lines
from holo_host.store import QueueStore
from tests.test_holo_host import FakeMemory, FakeRunner, close_service_handles


def _graph(tmp_path: Path) -> ProjectStateGraph:
    graph = ProjectStateGraph(tmp_path / "project_state.sqlite3")
    graph.ensure_schema()
    return graph


def test_creates_project_task_decision_open_question_nodes(tmp_path: Path) -> None:
    graph = _graph(tmp_path)

    graph.upsert_node("Holo", "Project", "Holo")
    graph.upsert_node("Holo", "Task", "Implement Stage155 project graph", status="active")
    graph.upsert_node("Holo", "Decision", "Use SQLite-backed normalized graph", status="accepted")
    graph.upsert_node("Holo", "OpenQuestion", "How should benchmarks use project state?", status="open")

    report = graph.get_project_state("Holo")
    node_types = {node["node_type"] for node in report["nodes"]}

    assert report["schema"] == PROJECT_STATE_GRAPH_SCHEMA
    assert {"Project", "Task", "Decision", "OpenQuestion"}.issubset(node_types)
    assert report["active_project"]["title"] == "Holo"
    assert report["active_tasks"][0]["title"] == "Implement Stage155 project graph"
    assert report["latest_decisions"][0]["title"] == "Use SQLite-backed normalized graph"
    assert report["open_questions"][0]["title"] == "How should benchmarks use project state?"


def test_adds_edges_and_preserves_source_evidence(tmp_path: Path) -> None:
    graph = _graph(tmp_path)
    task = graph.upsert_node("Holo", "Task", "Write deterministic tests", status="active")
    source = graph.upsert_node("Holo", "Source", "Codex Stage155 task", status="available")

    edge = graph.add_edge(
        "Holo",
        source["node_id"],
        task["node_id"],
        "supports",
        evidence={"source_ref": "stage155-test", "quote": "Tests are required"},
    )

    report = graph.get_project_state("Holo")
    assert edge["edge_type"] == "supports"
    assert report["edges"][0]["evidence"]["source_ref"] == "stage155-test"
    assert report["edges"][0]["source_node_id"] == source["node_id"]
    assert report["edges"][0]["target_node_id"] == task["node_id"]


def test_updates_task_status(tmp_path: Path) -> None:
    graph = _graph(tmp_path)
    graph.upsert_node("Holo", "Task", "Patch reply metadata", status="active")

    updated = graph.update_task_status("Holo", "Patch reply metadata", "completed")

    assert updated["status"] == "completed"
    report = graph.get_project_state("Holo")
    assert not [node for node in report["active_tasks"] if node["title"] == "Patch reply metadata"]
    assert report["nodes_by_status"]["completed"][0]["title"] == "Patch reply metadata"


def test_retrieves_open_loops(tmp_path: Path) -> None:
    graph = _graph(tmp_path)
    graph.upsert_node("Holo", "OpenQuestion", "Should Stage156 promote project deltas?", status="open")
    graph.upsert_node("Holo", "Risk", "Project state may overcapture noisy dialogue", status="open")
    graph.upsert_node("Holo", "Task", "Closed task", status="completed")

    loops = graph.get_open_loops("Holo")

    titles = {item["title"] for item in loops["items"]}
    assert "Should Stage156 promote project deltas?" in titles
    assert "Project state may overcapture noisy dialogue" in titles
    assert "Closed task" not in titles


def test_retrieves_next_actions(tmp_path: Path) -> None:
    graph = _graph(tmp_path)
    graph.upsert_node("Holo", "NextAction", "Run targeted Stage155 tests", status="open", metadata={"priority": 0.9})
    graph.upsert_node("Holo", "NextAction", "Old action", status="completed")

    actions = graph.get_next_actions("Holo")

    assert [item["title"] for item in actions["items"]] == ["Run targeted Stage155 tests"]


def test_stage150_packet_includes_active_project_state(tmp_path: Path) -> None:
    graph = _graph(tmp_path)
    graph.upsert_node("Holo", "Project", "Holo")
    graph.upsert_node("Holo", "Task", "Make project continuity reusable", status="active")
    graph.upsert_node("Holo", "OpenQuestion", "Which next action should run first?", status="open")
    graph.upsert_node("Holo", "Decision", "Keep graph deterministic and local", status="accepted")
    graph.upsert_node("Holo", "NextAction", "Expose CLI summary", status="open")
    project_state = graph.get_project_state("Holo")

    fabric = build_stage150_context_memory_fabric(
        user_text="Continue Stage155",
        channel="holo_cli",
        thread_key="holo_cli:main",
        chat_name="HoloCLI",
        sidecar={"project_state_graph": project_state},
    )

    packet = fabric["working_context_packet"]
    assert packet["active_project"]["title"] == "Holo"
    assert packet["active_tasks"][0]["title"] == "Make project continuity reusable"
    assert packet["open_questions"][0]["title"] == "Which next action should run first?"
    assert packet["latest_decisions"][0]["title"] == "Keep graph deterministic and local"
    assert packet["next_actions"][0]["title"] == "Expose CLI summary"
    assert any("Project State" in line for line in stage150_prompt_lines(fabric))


def test_detect_project_state_updates_from_turn_text() -> None:
    updates = detect_project_state_updates(
        project="Holo",
        user_text=(
            "Task: build project state graph. "
            "Decision: keep it local and deterministic. "
            "Open question: how should visual replay consume it? "
            "Risk: noisy chat should not become project truth. "
            "Next action: run Stage155 tests."
        ),
        source_ref="unit-test",
    )

    assert updates["schema"] == PROJECT_STATE_GRAPH_SCHEMA
    types = {node["node_type"] for node in updates["nodes"]}
    assert {"Project", "Task", "Decision", "OpenQuestion", "Risk", "NextAction"}.issubset(types)
    assert all(node["evidence"]["source_ref"] == "unit-test" for node in updates["nodes"])


def test_project_state_appears_in_reply_and_archive_metadata() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        config = load_config(repo_root=root)
        store = QueueStore(config.runtime.db_path)
        runner = FakeRunner("Recorded the project update.")
        memory = FakeMemory()
        service = HoloReplyService(config, store=store, runner=runner, memory=memory)
        try:
            result = service.handle_reply(
                {
                    "chat_name": "HoloCLI",
                    "sender": "Ran",
                    "text": (
                        "Task: build project state graph. "
                        "Decision: keep it local and deterministic. "
                        "Open question: how should visual replay consume it? "
                        "Next action: run Stage155 tests."
                    ),
                    "channel": "holo_cli",
                    "thread_key": "holo_cli:main",
                    "message_id": "stage155-reply-1",
                    "project": "Holo",
                }
            )

            assert result["action"] == "reply"
            assert result["project_state_graph"]["schema"] == PROJECT_STATE_GRAPH_SCHEMA
            assert result["project_state_update"]["applied_count"] >= 4
            stored_records = memory.archived_records or memory.observed_records
            archive_meta = stored_records[-1]["metadata"]
            assert archive_meta["project_state_graph"]["schema"] == PROJECT_STATE_GRAPH_SCHEMA
            assert archive_meta["project_state_update"]["applied_count"] >= 4
        finally:
            close_service_handles(service)


def test_stage135_topology_includes_project_state_graph_node(tmp_path: Path) -> None:
    graph = _graph(tmp_path)
    graph.upsert_node("Holo", "Project", "Holo")
    graph.upsert_node("Holo", "Task", "Make state visible", status="active")
    graph.upsert_node("Holo", "OpenQuestion", "What remains blocked?", status="open")
    graph.upsert_node("Holo", "NextAction", "Inspect topology", status="open")

    topology = build_stage135_i_state_topology(
        user_text="Show project continuity",
        channel="holo_cli",
        thread_key="holo_cli:main",
        chat_name="HoloCLI",
        project_state_graph=graph.get_project_state("Holo"),
    )

    assert topology["metrics"]["project_state_graph_node_count"] == 1
    assert topology["metrics"]["project_state_graph_open_loop_count"] >= 1
    assert topology["metrics"]["project_state_graph_next_action_count"] == 1
    assert any(node["id"] == "project_state_graph" for node in topology["nodes"])
