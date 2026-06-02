from __future__ import annotations

from pathlib import Path

from kernel_v3 import cli
from kernel_v3.agent import AgentRuntime
from kernel_v3.chat import ChatRuntime, ThreadTranscriptStore
from kernel_v3.chat.console import known_chat_threads, thread_history
from kernel_v3.journal import JournalStore


def test_thread_transcripts_are_split_by_thread(tmp_path: Path):
    journal = JournalStore(tmp_path / "global.jsonl", index_path=tmp_path / "global.sqlite")
    thread_store = ThreadTranscriptStore(tmp_path / "threads")
    chat = ChatRuntime(
        journal=journal,
        agent_runtime=AgentRuntime(journal=journal),
        thread_store=thread_store,
    )

    chat.receive("hello from a", thread_id="thread-a")
    chat.receive("hello from b", thread_id="thread-b")

    thread_a = thread_store.thread_path("thread-a")
    thread_b = thread_store.thread_path("thread-b")
    assert thread_a.exists()
    assert thread_b.exists()
    assert thread_a != thread_b
    assert "hello from a" in thread_a.read_text(encoding="utf-8")
    assert "hello from b" not in thread_a.read_text(encoding="utf-8")
    assert "hello from b" in thread_b.read_text(encoding="utf-8")
    assert "hello from a" not in thread_b.read_text(encoding="utf-8")

    threads = known_chat_threads(chat)
    assert {item["thread_id"] for item in threads} == {"thread-a", "thread-b"}
    assert all(item.get("transcript_path") for item in threads)

    history_a = thread_history(chat, "thread-a", limit=10)
    assert [item["role"] for item in history_a] == ["user", "assistant"]
    assert history_a[0]["text"] == "hello from a"


def test_cli_defaults_use_state_storage_layout(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOLO_V3_STATE_DIR", str(tmp_path / ".state/kernel_v3"))

    exit_code = cli.main(["chat", "--offline", "--thread", "layout-thread", "--once", "hello"])

    assert exit_code == 0
    assert (tmp_path / ".state/kernel_v3/journal/global.jsonl").exists()
    assert (tmp_path / ".state/kernel_v3/journal/global.sqlite").exists()
    assert (tmp_path / ".state/kernel_v3/threads/layout-thread/thread.jsonl").exists()
    assert (tmp_path / ".state/kernel_v3/memory/memory.sqlite").exists()


def test_thread_listing_merges_legacy_journal_threads_and_transcripts(tmp_path: Path):
    journal = JournalStore(tmp_path / "legacy.jsonl", index_path=tmp_path / "legacy.sqlite")
    journal.append(
        task_id=None,
        run_id="chat-thread-legacy-thread",
        step_id=None,
        kind="chat_turn",
        data={"thread_id": "legacy-thread", "role": "user", "text": "old hello"},
        state_delta={"thread_id": "legacy-thread"},
    )
    thread_store = ThreadTranscriptStore(tmp_path / "threads")
    chat = ChatRuntime(
        journal=journal,
        agent_runtime=AgentRuntime(journal=journal),
        thread_store=thread_store,
    )

    chat.receive("new hello", thread_id="new-thread")

    threads = known_chat_threads(chat)
    assert {item["thread_id"] for item in threads} == {"legacy-thread", "new-thread"}
    assert thread_history(chat, "legacy-thread", limit=10)[0]["text"] == "old hello"
    assert thread_history(chat, "new-thread", limit=10)[0]["text"] == "new hello"
