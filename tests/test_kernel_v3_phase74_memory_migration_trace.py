import json
from pathlib import Path

from kernel_v3 import cli
from kernel_v3.agent.runtime import AgentRuntime
from kernel_v3.journal import JournalStore
from kernel_v3.memory import MemoryPipeline, MemoryStore
from kernel_v3.memory.migration import migrate_semantic_intake_records
from kernel_v3.processors.testing import fake_fabric
from kernel_v3.trace import TraceRenderer


def test_phase74_migrates_existing_semantic_intake_once():
    journal = JournalStore.in_memory()
    AgentRuntime(journal=journal, processor_fabric=_memory_fabric(journal, "我偏好中文短答")).run(
        "记住我偏好中文短答",
        thread_id="thread-migrate",
        semantic_mode="model",
    )
    store = MemoryStore.in_memory(clock_ms=_clock())

    first = migrate_semantic_intake_records(journal=journal, store=store)
    second = migrate_semantic_intake_records(journal=journal, store=store)

    assert first.scanned_records == 1
    assert first.migrated_records == 1
    assert len(first.proposals) == 1
    assert second.migrated_records == 0
    assert len(store.proposals()) == 1
    assert journal.records(kind="memory_migration")


def test_phase74_memory_export_and_trace_show_audit_chain():
    journal = JournalStore.in_memory()
    AgentRuntime(journal=journal, processor_fabric=_memory_fabric(journal, "我偏好中文短答")).run(
        "记住我偏好中文短答",
        thread_id="thread-export",
        semantic_mode="model",
    )
    store = MemoryStore.in_memory(clock_ms=_clock())
    report = migrate_semantic_intake_records(journal=journal, store=store)
    committed = MemoryPipeline(store=store, journal=journal).approve_proposal(report.proposals[0]).committed_items[0]

    exported = store.export_item(committed.memory_id)
    trace = TraceRenderer(journal).render_memory_trace("task-1")

    assert exported["item"]["memory_id"] == committed.memory_id
    assert exported["proposals"][0]["proposal_id"] == report.proposals[0]
    assert exported["audit_records"]
    assert "memory_migration" in trace
    assert "memory_proposal_approved" in trace


def test_phase74_cli_migrates_approves_and_exports_memory(tmp_path: Path, capsys):
    journal_path = tmp_path / "journal.jsonl"
    index_path = tmp_path / "journal.sqlite"
    memory_log = tmp_path / "memory.jsonl"
    memory_index = tmp_path / "memory.sqlite"
    journal = JournalStore(journal_path, index_path=index_path)
    AgentRuntime(
        journal=journal,
        processor_fabric=_memory_fabric(journal, "concise Chinese replies"),
    ).run(
        "remember my preference: concise Chinese replies",
        thread_id="cli-migrate",
        semantic_mode="model",
    )
    base = [
        "--journal",
        str(journal_path),
        "--index",
        str(index_path),
        "--memory-log",
        str(memory_log),
        "--memory-index",
        str(memory_index),
    ]

    assert cli.main([*base, "memory", "migrate-semantic"]) == 0
    migrated = json.loads(capsys.readouterr().out)
    proposal_id = migrated["migration"]["proposals"][0]

    assert cli.main([*base, "memory", "approve", proposal_id]) == 0
    approved = json.loads(capsys.readouterr().out)
    memory_id = approved["result"]["committed_items"][0]["memory_id"]

    assert cli.main([*base, "memory", "export", memory_id]) == 0
    exported = json.loads(capsys.readouterr().out)
    assert exported["export"]["item"]["memory_id"] == memory_id

    assert cli.main([*base, "memory-trace", "task-1"]) == 0
    trace = capsys.readouterr().out
    assert "Memory Trace task-1" in trace
    assert "memory_migration" in trace


def _memory_fabric(journal: JournalStore, text: str):
    return fake_fabric(
        {
            "semantic.intake": {
                "primary_intent": "memory_write",
                "suggested_mode": "clarify_first",
                "compound": False,
                "requires_clarification": True,
                "intents": [
                    {
                        "kind": "memory_write",
                        "text": text,
                        "sequence_index": 1,
                        "required_capabilities": ["durable_memory:write"],
                        "risk": "write",
                        "status": "needs_review",
                        "metadata": {},
                    }
                ],
                "blocked_capabilities": ["durable_memory:write"],
                "warnings": [],
                "response_hint": None,
                "clarification_question": None,
            }
        },
        journal=journal,
    )


def _clock(start: int = 1_000):
    current = start

    def tick() -> int:
        nonlocal current
        current += 1
        return current

    return tick
