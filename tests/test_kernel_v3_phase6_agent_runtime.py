import json
import subprocess
import sys
from pathlib import Path

from kernel_v3.agent import AgentRuntime
from kernel_v3.agent.workloop import WorkloopConfig
from kernel_v3.context import ArtifactStore
from kernel_v3.journal import JournalStore
from kernel_v3.processors import FakeJsonProvider, FakeMalformedJsonProvider, ProcessorFabric, ProcessorRouter
from kernel_v3.research import ResearchCorpusStore, corpus_document_from_retrieval
from kernel_v3.retrieval import FakeFetchProvider, FakeSearchProvider, RetrievalOperator
from kernel_v3.retrieval.contracts import FetchedDocument, SearchGoal, SearchSource
from kernel_v3.trace import TraceRenderer


def test_phase6_direct_answer_completes_in_one_loop_and_journals_final_answer():
    journal = JournalStore.in_memory()
    result = AgentRuntime(journal=journal).run("explain Holo briefly", mode="direct")

    assert result.status == "completed"
    assert result.final_answer is not None
    assert "离线 host fallback" in result.final_answer["answer"]
    assert "Direct answer:" not in result.final_answer["answer"]
    assert _action_names(journal, result.task_id) == ["respond"]
    assert journal.records(task_id=result.task_id, kind="agent_final_answer")


def test_phase6_retrieval_answer_uses_retrieval_run_then_synthesizer():
    journal = JournalStore.in_memory()
    artifacts = ArtifactStore.in_memory()
    corpus = _corpus_with_document(artifacts, query_text="Kernel v3 retrieval")
    result = AgentRuntime(journal=journal, artifact_store=artifacts, research_corpus_store=corpus).run(
        "Kernel v3 retrieval",
        mode="retrieval",
    )

    assert result.status == "completed"
    assert result.final_answer is not None
    assert _action_names(journal, result.task_id) == ["retrieval.run"]
    assert journal.records(task_id=result.task_id, kind="retrieval_report")
    assert journal.records(task_id=result.task_id, kind="retrieval_evidence")
    assert journal.records(task_id=result.task_id, kind="retrieval_citation")
    assert journal.records(task_id=result.task_id, kind="processor_request")
    assert result.final_answer["citation_refs"]
    assert result.final_answer["used_evidence"]
    capabilities = journal.records(task_id=result.task_id, kind="retrieval_query_plan")[0].data["diagnostics"]["provider_capabilities"]
    assert capabilities[0]["provider_id"] == "research_corpus"


def test_phase6_default_retrieval_without_source_returns_failure_report_not_fake_evidence():
    journal = JournalStore.in_memory()
    result = AgentRuntime(journal=journal, artifact_store=ArtifactStore.in_memory()).run("Kernel v3 retrieval", mode="retrieval")

    assert result.status == "failed"
    assert result.final_answer is None
    assert result.failure_report is not None
    capabilities = journal.records(task_id=result.task_id, kind="retrieval_query_plan")[0].data["diagnostics"]["provider_capabilities"]
    assert capabilities[0]["provider_id"] == "unconfigured_search"
    assert not journal.records(task_id=result.task_id, kind="retrieval_evidence")
    assert not journal.records(task_id=result.task_id, kind="retrieval_citation")


def test_phase6_retrieval_answer_refuses_final_when_citations_required_but_absent():
    journal = JournalStore.in_memory()
    runtime = AgentRuntime(
        journal=journal,
        artifact_store=ArtifactStore.in_memory(),
        retrieval_operator=RetrievalOperator(
            search_provider=FakeSearchProvider({"missing evidence": []}),
            fetch_provider=FakeFetchProvider({}),
        ),
        workloop_config=WorkloopConfig(repeated_action_limit=2, repeated_missing_evidence_limit=2, no_progress_step_limit=2),
    )

    result = runtime.run("missing evidence", mode="retrieval", citations_required=True)

    assert result.status == "failed"
    assert result.final_answer is None
    assert result.failure_report is not None
    assert result.failure_report["reason"] == "repeated_no_progress"
    assert "sufficient_retrieval_evidence" in result.failure_report["missing_evidence"]
    assert journal.records(task_id=result.task_id, kind="agent_failure_report")


def test_phase6_workspace_answer_searches_reads_and_synthesizes_without_network():
    journal = JournalStore.in_memory()
    runtime = AgentRuntime(
        journal=journal,
        workspace_files={"README.md": "Holo Kernel v3 workspace grounded answer."},
    )

    result = runtime.run("read README.md and answer", mode="workspace")

    assert result.status == "completed"
    assert result.final_answer is not None
    assert _action_names(journal, result.task_id) == ["workspace.search", "file.read"]
    assert "workspace-cite-2" in result.final_answer["citation_refs"]
    assert "workspace grounded answer" in result.final_answer["answer"]
    assert not journal.records(task_id=result.task_id, kind="retrieval_report")


def test_phase6_model_workspace_loop_recovers_path_alias_and_runs_multiple_steps():
    journal = JournalStore.in_memory()
    fabric = ProcessorFabric(
        providers={
            "fake_json": FakeJsonProvider(
                {
                    "planner.propose": [
                        {
                            "action_id": "act-search-with-path",
                            "kind": "tool",
                            "name": "workspace.search",
                            "description": "search using a path alias",
                            "payload": {"path": "docs/KERNEL_V3_AGENT_LOOP.md"},
                            "score": 0.9,
                            "reasons": ["locate the requested document"],
                            "side_effect_class": "read",
                        },
                        {
                            "action_id": "act-read-doc",
                            "kind": "tool",
                            "name": "file.read",
                            "description": "read the requested document",
                            "payload": {"path": "docs/KERNEL_V3_AGENT_LOOP.md"},
                            "score": 0.9,
                            "reasons": ["read evidence before answering"],
                            "side_effect_class": "read",
                        },
                    ],
                    "evaluator.assess": [
                        {
                            "status": "continue",
                            "answer": None,
                            "stop_reason": None,
                            "missing_evidence": ["file.read observation"],
                        },
                        {
                            "status": "final_answer_ready",
                            "answer": "ready",
                            "stop_reason": "completed",
                            "missing_evidence": [],
                        },
                    ],
                    "synthesizer.answer": {
                        "answer": "Kernel v3 supports multiple loop steps and host-owned termination.",
                        "citation_refs": ["workspace-cite-2"],
                        "confidence": 0.9,
                        "limitations": [],
                        "used_evidence": ["workspace-evidence-2"],
                    },
                }
            )
        },
        router=ProcessorRouter(default_provider="fake_json", default_model="fake-json"),
        journal=journal,
    )
    runtime = AgentRuntime(
        journal=journal,
        processor_fabric=fabric,
        workspace_files={
            "docs/KERNEL_V3_AGENT_LOOP.md": "Kernel v3 supports multiple loop steps and host-owned termination."
        },
    )

    result = runtime.run(
        "read docs/KERNEL_V3_AGENT_LOOP.md and summarize loop behavior",
        mode="workspace",
        planner_mode="model",
        evaluator_mode="model",
        synthesizer_mode="model",
    )

    assert result.status == "completed"
    assert _action_names(journal, result.task_id) == ["workspace.search", "file.read"]
    observations = journal.records(task_id=result.task_id, kind="observation")
    assert observations[0].data["content"]["query"] == "docs/KERNEL_V3_AGENT_LOOP.md"
    assert observations[1].data["source"] == "tool:file.read"
    decisions = [record.data["decision"] for record in journal.records(task_id=result.task_id, kind="termination_decision")]
    assert decisions == ["continue", "final_answer"]
    assert result.final_answer["citation_refs"] == ["workspace-cite-2"]


def test_phase6_workspace_resume_does_not_finalize_from_stale_file_observation():
    journal = JournalStore.in_memory()
    first = AgentRuntime(
        journal=journal,
        workspace_files={"README.md": "old workspace evidence"},
    ).run("read README.md", mode="workspace")

    second = AgentRuntime(
        journal=journal,
        workspace_files={"README.md": "old workspace evidence"},
    ).resume(first.task_id, "read MISSING.md", mode="workspace")

    assert first.status == "completed"
    assert second.status == "needs_user_input"
    assert second.final_answer is None
    run2_finals = [
        record for record in journal.records(task_id=first.task_id, kind="agent_final_answer")
        if record.run_id == "run-2"
    ]
    assert run2_finals == []
    run2_sufficiency = [
        record.data for record in journal.records(task_id=first.task_id, kind="evidence_sufficiency")
        if record.run_id == "run-2"
    ]
    assert run2_sufficiency
    assert all(item["evidence_count"] == 0 for item in run2_sufficiency)


def test_phase6_ambiguous_workspace_request_asks_user():
    journal = JournalStore.in_memory()
    result = AgentRuntime(journal=journal).run("read the file", mode="workspace")

    assert result.status == "needs_user_input"
    assert result.final_answer is None
    assert _action_names(journal, result.task_id) == ["ask_user"]
    observation = journal.records(task_id=result.task_id, kind="observation")[0]
    assert observation.data["status"] == "needs_user_input"


def test_phase6_failed_retrieval_returns_failure_report_not_invented_answer():
    journal = JournalStore.in_memory()
    runtime = AgentRuntime(
        journal=journal,
        retrieval_operator=RetrievalOperator(
            search_provider=FakeSearchProvider({"no source": []}),
            fetch_provider=FakeFetchProvider({}),
        ),
        workloop_config=WorkloopConfig(repeated_action_limit=2, repeated_missing_evidence_limit=2, no_progress_step_limit=2),
    )

    result = runtime.run("no source", mode="retrieval")

    assert result.status == "failed"
    assert result.final_answer is None
    assert result.failure_report is not None
    assert result.failure_report["attempted_actions"] == ["retrieval.run", "retrieval.run"]
    assert result.failure_report["next_possible_action"] == "refine_query_or_add_sources"


def test_phase6_model_planner_failure_returns_failure_report_not_user_prompt():
    journal = JournalStore.in_memory()
    fabric = ProcessorFabric(
        providers={"fake_malformed_json": FakeMalformedJsonProvider("not-json")},
        router=ProcessorRouter(default_provider="fake_malformed_json", default_model="fake-malformed-json"),
        journal=journal,
    )

    result = AgentRuntime(journal=journal, processor_fabric=fabric).run(
        "answer directly",
        mode="direct",
        planner_mode="model",
    )

    assert result.status == "failed"
    assert result.failure_report is not None
    assert result.failure_report["reason"] == "model_planner_processor_failed"
    assert result.failure_report["user_help_needed"] is False
    assert result.failure_report["next_possible_action"] == "retry_model_planner_or_reduce_context"
    assert "planner_action" in result.failure_report["missing_evidence"]
    assert _action_names(journal, result.task_id) == ["ask_user"]


def test_phase6_model_planner_failure_in_retrieval_mode_is_not_misdiagnosed_as_missing_report():
    journal = JournalStore.in_memory()
    fabric = ProcessorFabric(
        providers={"fake_malformed_json": FakeMalformedJsonProvider("not-json")},
        router=ProcessorRouter(default_provider="fake_malformed_json", default_model="fake-malformed-json"),
        journal=journal,
    )

    result = AgentRuntime(journal=journal, processor_fabric=fabric, artifact_store=ArtifactStore.in_memory()).run(
        "search current finance evidence",
        mode="retrieval",
        planner_mode="model",
        evaluator_mode="model",
    )

    assert result.status == "failed"
    assert result.failure_report is not None
    assert result.failure_report["reason"] == "model_planner_processor_failed"
    assert result.failure_report["next_possible_action"] == "retry_model_planner_or_reduce_context"
    assert "planner_action" in result.failure_report["missing_evidence"]
    assert not journal.records(task_id=result.task_id, kind="retrieval_report")


def test_phase6_trace_evidence_artifacts_and_retrieval_trace_render_complete_path():
    journal = JournalStore.in_memory()
    artifacts = ArtifactStore.in_memory()
    corpus = _corpus_with_document(artifacts, query_text="Kernel v3 retrieval")
    result = AgentRuntime(journal=journal, artifact_store=artifacts, research_corpus_store=corpus).run(
        "Kernel v3 retrieval",
        mode="retrieval",
    )
    renderer = TraceRenderer(journal)

    trace = renderer.render_task(result.task_id, verbose=True)
    evidence = renderer.render_evidence(result.task_id)
    artifacts = renderer.render_artifacts(result.task_id)
    retrieval_trace = renderer.render_retrieval_trace(result.task_id)

    assert "Trace task-" in trace
    assert "agent_final_answer" in trace
    assert "Evidence task-" in evidence
    assert "Artifacts task-" in artifacts
    assert "Retrieval Trace task-" in retrieval_trace
    assert "report=report-goal-agent-retrieval status=sufficient" in retrieval_trace


def test_phase6_citations_required_blocks_direct_mode_without_citations():
    journal = JournalStore.in_memory()
    result = AgentRuntime(journal=journal).run("answer without evidence", mode="direct", citations_required=True)

    assert result.status == "failed"
    assert result.final_answer is None
    assert result.failure_report["reason"] == "citations_required_but_missing"


def test_phase6_loop_controller_remains_tool_name_agnostic():
    source = Path("kernel_v3/loop.py").read_text(encoding="utf-8")

    for forbidden in ["retrieval.run", "workspace.search", "file.read", "deepseek", "agent_recipe"]:
        assert forbidden not in source


def test_phase6_cli_agent_answer_and_inspect_run(tmp_path: Path):
    journal = tmp_path / "journal.jsonl"
    index = tmp_path / "journal.sqlite"
    artifact_log = tmp_path / "artifacts.jsonl"
    corpus_log = tmp_path / "corpus.jsonl"
    corpus_index = tmp_path / "corpus.sqlite"

    _run_cli(
        "--journal",
        str(journal),
        "--index",
        str(index),
        "--artifact-log",
        str(artifact_log),
        "--corpus-log",
        str(corpus_log),
        "--corpus-index",
        str(corpus_index),
        "retrieve",
        "Kernel v3 retrieval",
        "--body",
        "Kernel v3 retrieval corpus evidence from local indexed source.",
        "--index-corpus",
    )

    agent = _run_cli(
        "--journal",
        str(journal),
        "--index",
        str(index),
        "--artifact-log",
        str(artifact_log),
        "--corpus-log",
        str(corpus_log),
        "--corpus-index",
            str(corpus_index),
            "agent",
            "--offline",
            "Kernel v3 retrieval",
            "--mode",
            "retrieval",
    )
    agent_payload = json.loads(agent.stdout)
    assert agent_payload["status"] == "completed"
    assert agent_payload["final_answer"]["citation_refs"]

    answer = _run_cli(
        "--journal",
        str(journal),
        "--index",
        str(index),
        "--artifact-log",
        str(artifact_log),
        "--corpus-log",
        str(corpus_log),
        "--corpus-index",
        str(corpus_index),
        "answer",
        "Kernel v3 retrieval",
        "--citations-required",
    )
    answer_payload = json.loads(answer.stdout)
    assert answer_payload["status"] == "completed"
    assert answer_payload["final_answer"]["citation_refs"]

    inspect = _run_cli("--journal", str(journal), "--index", str(index), "inspect-run", agent_payload["task_id"])
    inspect_payload = json.loads(inspect.stdout)
    assert "Trace " + agent_payload["task_id"] in inspect_payload["trace"]
    assert "Retrieval Trace " + agent_payload["task_id"] in inspect_payload["retrieval_trace"]


def _action_names(journal: JournalStore, task_id: str) -> list[str]:
    names = []
    for record in journal.records(task_id=task_id, kind="action"):
        names.append(str(record.data.get("name") or record.data.get("kind")))
    return names


def _run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "kernel_v3.cli", *args],
        cwd=Path(__file__).resolve().parents[1],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )


def _corpus_with_document(artifacts: ArtifactStore, *, query_text: str) -> ResearchCorpusStore:
    corpus = ResearchCorpusStore.in_memory(clock_ms=lambda: 101)
    uri = "local://kernel-v3/retrieval-corpus"
    title = "Kernel v3 retrieval corpus source"
    body = f"{query_text} corpus evidence from a local indexed source."
    source = SearchSource(
        source_id="src-local-corpus",
        uri=uri,
        title=title,
        snippet=query_text,
        provider="local_corpus_seed",
    )
    artifact = artifacts.write_blob(
        kind="retrieval_fetched_document",
        payload=body,
        metadata={"uri": uri, "source_id": source.source_id, "title": title},
    )
    corpus.record_document(
        corpus_document_from_retrieval(
            document=FetchedDocument(
                document_id="doc-local-corpus",
                goal_id="goal-local-corpus",
                source_id=source.source_id,
                uri=uri,
                title=title,
                artifact_id=artifact.artifact_id,
                payload_hash=artifact.payload_hash,
                preview=body[:160],
                size_bytes=len(body.encode("utf-8")),
                metadata={"mime_type": "text/plain"},
            ),
            source=source,
            goal=SearchGoal(goal_id="goal-local-corpus", query=query_text),
            task_id="task-local-corpus",
            run_id="run-local-corpus",
            fetched_at_ms=101,
        )
    )
    return corpus
