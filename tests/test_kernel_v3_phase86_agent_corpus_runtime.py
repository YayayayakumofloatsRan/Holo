import json
import subprocess
import sys
from pathlib import Path

from kernel_v3.agent import AgentRuntime
from kernel_v3.chat import ChatRuntime
from kernel_v3.context import ArtifactStore
from kernel_v3.journal import JournalStore
from kernel_v3.processors.testing import fake_fabric
from kernel_v3.research import ResearchCorpusStore
from kernel_v3.resident import ResidentQueue, ResidentRuntime


def test_phase86_agent_runtime_indexes_and_reuses_configured_corpus() -> None:
    journal = JournalStore.in_memory()
    artifacts = ArtifactStore.in_memory()
    corpus = ResearchCorpusStore.in_memory(clock_ms=lambda: 606)
    runtime = AgentRuntime(journal=journal, artifact_store=artifacts, research_corpus_store=corpus)

    first = runtime.run("AAPL 2024 revenue", mode="retrieval")
    second = runtime.run("AAPL 2024 revenue", mode="retrieval")

    assert first.status == "completed"
    assert second.status == "completed"
    assert len(corpus.documents()) == 1
    assert [event["event_type"] for event in corpus.audit_records()] == [
        "corpus_document_recorded",
        "corpus_document_reobserved",
    ]
    second_search = journal.records(task_id=second.task_id, kind="retrieval_search_attempt")[0].data
    assert second_search["sources"][0]["provider"] == "research_corpus"
    assert second_search["sources"][0]["metadata"]["corpus_document_id"]
    assert journal.records(task_id=second.task_id, kind="retrieval_corpus_document")


def test_phase86_resident_runtime_reuses_configured_corpus_across_messages(tmp_path: Path) -> None:
    queue = ResidentQueue(tmp_path / "resident.sqlite", clock_ms=_clock())
    journal = JournalStore.in_memory()
    artifacts = ArtifactStore.in_memory()
    corpus = ResearchCorpusStore.in_memory(clock_ms=lambda: 707)
    fabric = fake_fabric({"semantic.intake": _retrieval_intake()}, journal=journal)
    agent = AgentRuntime(
        journal=journal,
        artifact_store=artifacts,
        processor_fabric=fabric,
        research_corpus_store=corpus,
    )
    chat = ChatRuntime(journal=journal, agent_runtime=agent, semantic_mode="model")
    runtime = ResidentRuntime(queue=queue, chat_runtime=chat, worker_id="worker-corpus", journal=journal)

    queue.enqueue(thread_id="resident-corpus", text="AAPL 2024 revenue", message_id="in-corpus-1")
    queue.enqueue(thread_id="resident-corpus", text="AAPL 2024 revenue", message_id="in-corpus-2")
    first = runtime.run_once()
    second = runtime.run_once()

    assert first.status == "processed"
    assert second.status == "processed"
    assert len(corpus.documents()) == 1
    second_outbox = queue.outbox_messages()[1]
    second_search = journal.records(task_id=second_outbox.task_id, kind="retrieval_search_attempt")[0].data
    assert second_search["sources"][0]["provider"] == "research_corpus"
    assert second_outbox.payload["final_answer"]["citation_refs"]


def test_phase86_cli_agent_wires_persistent_corpus_store(tmp_path: Path) -> None:
    journal_path = tmp_path / "journal.jsonl"
    index_path = tmp_path / "journal.sqlite"
    artifact_path = tmp_path / "artifacts.jsonl"
    corpus_path = tmp_path / "corpus.jsonl"
    corpus_index = tmp_path / "corpus.sqlite"
    base_args = [
        "--journal",
        str(journal_path),
        "--index",
        str(index_path),
        "--artifact-log",
        str(artifact_path),
        "--corpus-log",
        str(corpus_path),
        "--corpus-index",
        str(corpus_index),
    ]

    first = json.loads(_run_cli(*base_args, "agent", "AAPL 2024 revenue", "--mode", "retrieval").stdout)
    second = json.loads(_run_cli(*base_args, "agent", "AAPL 2024 revenue", "--mode", "retrieval").stdout)
    journal = JournalStore(journal_path, index_path=index_path)

    assert first["status"] == "completed"
    assert second["status"] == "completed"
    second_search = journal.records(task_id=second["task_id"], kind="retrieval_search_attempt")[0].data
    assert second_search["sources"][0]["provider"] == "research_corpus"
    assert "corpus_document_reobserved" in corpus_path.read_text(encoding="utf-8")


def _retrieval_intake() -> dict[str, object]:
    return {
        "primary_intent": "retrieval_research",
        "suggested_mode": "retrieval_answer",
        "compound": False,
        "requires_clarification": False,
        "intents": [
            {
                "kind": "retrieval_research",
                "text": "research resident corpus evidence",
                "sequence_index": 1,
                "required_capabilities": ["retrieval.run"],
                "risk": "read",
                "status": "ready",
                "metadata": {},
            }
        ],
        "blocked_capabilities": [],
        "warnings": [],
        "response_hint": None,
        "clarification_question": None,
    }


def _clock(start: int = 1_000):
    value = {"now": start}

    def tick() -> int:
        value["now"] += 1
        return value["now"]

    return tick


def _run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "kernel_v3.cli", *args],
        cwd=Path(__file__).resolve().parents[1],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )
