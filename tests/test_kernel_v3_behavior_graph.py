import json
from pathlib import Path

from kernel_v3 import cli
from kernel_v3.behavior_graph import BehaviorGraphBuilder, render_behavior_graph_dot
from kernel_v3.journal import JournalStore


def test_behavior_graph_links_model_action_retrieval_evidence_and_answer() -> None:
    journal = JournalStore.in_memory()
    _populate_retrieval_task(journal)

    graph = BehaviorGraphBuilder(journal).build_task_graph("task-graph")

    node_types = graph.diagnostics["node_types"]
    edge_types = graph.diagnostics["edge_types"]
    assert graph.schema == "holo.kernel_v3.behavior_graph.v1"
    assert node_types["processor_request"] == 1
    assert node_types["processor_result"] == 1
    assert node_types["action"] == 1
    assert node_types["search"] == 1
    assert node_types["source"] == 1
    assert node_types["evidence"] == 1
    assert node_types["citation"] == 1
    assert node_types["final_answer"] == 1
    assert edge_types["processor_result"] == 1
    assert edge_types["found_source"] == 1
    assert edge_types["supports_evidence"] >= 1
    assert edge_types["cited_by"] == 1
    assert edge_types["used_in_answer"] == 1

    dumped = json.dumps(graph.to_dict(), ensure_ascii=False)
    assert "Apple net sales were" in dumped
    assert "sk-secret" not in dumped


def test_behavior_graph_cli_outputs_dot(tmp_path: Path, capsys) -> None:
    journal_path = tmp_path / "journal.jsonl"
    index_path = tmp_path / "journal.sqlite"
    journal = JournalStore(journal_path, index_path=index_path)
    _populate_retrieval_task(journal)

    code = cli.main(
        [
            "--journal",
            str(journal_path),
            "--index",
            str(index_path),
            "behavior-graph",
            "task-graph",
            "--format",
            "dot",
        ]
    )

    assert code == 0
    out = capsys.readouterr().out
    assert "digraph HoloBehaviorGraph" in out
    assert "Action: retrieval.run" in out
    assert "Citation: cite-1" in out


def test_behavior_graph_cli_writes_json(tmp_path: Path) -> None:
    journal_path = tmp_path / "journal.jsonl"
    index_path = tmp_path / "journal.sqlite"
    output_path = tmp_path / "graph.json"
    journal = JournalStore(journal_path, index_path=index_path)
    _populate_retrieval_task(journal)

    code = cli.main(
        [
            "--journal",
            str(journal_path),
            "--index",
            str(index_path),
            "behavior-graph",
            "task-graph",
            "--output",
            str(output_path),
        ]
    )

    assert code == 0
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["schema"] == "holo.kernel_v3.behavior_graph.v1"
    assert payload["diagnostics"]["node_count"] >= 10


def _populate_retrieval_task(journal: JournalStore) -> None:
    journal.append(
        task_id="task-graph",
        run_id="run-1",
        step_id="step-0",
        kind="processor_request",
        data={
            "request_id": "req-1",
            "processor": "planner",
            "parameters": {"task_type": "planner.propose"},
            "prompt": "Do not leak token=sk-secret-value.",
            "context_id": "ctx-1",
        },
    )
    journal.append(
        task_id="task-graph",
        run_id="run-1",
        step_id="step-0",
        kind="processor_result",
        data={"request_id": "req-1", "status": "ok", "output": {"task_type": "planner.propose"}},
    )
    journal.append(
        task_id="task-graph",
        run_id="run-1",
        step_id="step-1",
        kind="action",
        data={
            "action_id": "act-1",
            "kind": "tool",
            "name": "retrieval.run",
            "payload": {"goal": "Apple revenue"},
            "side_effect_class": "network",
        },
    )
    journal.append(
        task_id="task-graph",
        run_id="run-1",
        step_id="step-1",
        kind="retrieval_query_plan",
        data={"plan_id": "plan-1", "goal_id": "goal-1", "queries": [{"query": "Apple 10-K net sales"}]},
    )
    journal.append(
        task_id="task-graph",
        run_id="run-1",
        step_id="step-1",
        kind="retrieval_search_attempt",
        data={
            "attempt_id": "search-1",
            "goal_id": "goal-1",
            "query": "Apple 10-K net sales",
            "status": "ok",
            "sources": [{"source_id": "src-1", "title": "Apple 2024 Form 10-K", "uri": "https://sec.example/aapl"}],
        },
    )
    journal.append(
        task_id="task-graph",
        run_id="run-1",
        step_id="step-1",
        kind="retrieval_fetch_attempt",
        data={
            "fetch_id": "fetch-1",
            "source_id": "src-1",
            "uri": "https://sec.example/aapl",
            "status": "ok",
            "artifact_id": "art-1",
            "payload_hash": "hash-1",
            "size_bytes": 128,
        },
        artifact_refs=["art-1"],
    )
    journal.append(
        task_id="task-graph",
        run_id="run-1",
        step_id="step-1",
        kind="retrieval_extraction",
        data={
            "document": {"document_id": "doc-1", "title": "Apple 2024 Form 10-K", "artifact_id": "art-1"},
            "spans": [{"span_id": "span-1"}],
        },
    )
    journal.append(
        task_id="task-graph",
        run_id="run-1",
        step_id="step-1",
        kind="retrieval_evidence",
        data={
            "evidence_id": "ev-1",
            "source_id": "src-1",
            "artifact_id": "art-1",
            "score": 0.98,
            "text": "Apple net sales were reported in the filing.",
        },
    )
    journal.append(
        task_id="task-graph",
        run_id="run-1",
        step_id="step-1",
        kind="retrieval_citation",
        data={"citation_id": "cite-1", "evidence_id": "ev-1", "artifact_id": "art-1", "quote": "net sales"},
    )
    journal.append(
        task_id="task-graph",
        run_id="run-1",
        step_id="step-1",
        kind="observation",
        data={
            "observation_id": "obs-1",
            "action_id": "act-1",
            "kind": "tool",
            "status": "ok",
            "source": "tool:retrieval.run",
            "content": {"report_id": "report-1"},
        },
    )
    journal.append(
        task_id="task-graph",
        run_id="run-1",
        step_id="step-1",
        kind="feedback",
        data={"feedback_id": "fb-1", "status": "final_answer_ready", "observation_id": "obs-1", "missing_evidence": []},
    )
    journal.append(
        task_id="task-graph",
        run_id="run-1",
        step_id="step-2",
        kind="agent_final_answer",
        data={"answer": "Apple net sales were reported.", "citation_refs": ["cite-1"], "confidence": 0.9},
    )
