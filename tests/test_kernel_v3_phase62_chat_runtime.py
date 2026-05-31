import json
import subprocess
import sys
from pathlib import Path

from kernel_v3.agent import AgentRuntime
from kernel_v3.chat import ChatRuntime
from kernel_v3.journal import JournalStore


def test_phase62_two_turns_share_thread_id():
    journal = JournalStore.in_memory()
    chat = ChatRuntime(journal=journal, agent_runtime=AgentRuntime(journal=journal))

    first = chat.receive("hello", thread_id="thread-a")
    second = chat.receive("what next", thread_id="thread-a")

    assert first.thread_id == "thread-a"
    assert second.thread_id == "thread-a"
    assert {record.data["thread_id"] for record in journal.records(kind="chat_turn")} == {"thread-a"}


def test_phase62_ask_user_result_creates_pending_question():
    journal = JournalStore.in_memory()
    chat = ChatRuntime(journal=journal, agent_runtime=AgentRuntime(journal=journal))

    result = chat.receive("read the file", thread_id="thread-pending")
    state = chat.build_thread_state("thread-pending")

    assert result.status == "needs_user_input"
    assert result.pending_question is not None
    assert state.pending_question is not None
    assert state.pending_question["task_id"] == result.task_id
    assert "question" in state.pending_question


def test_phase62_next_user_answer_resumes_same_task_and_clears_pending_state():
    journal = JournalStore.in_memory()
    agent = AgentRuntime(journal=journal, workspace_files={"README.md": "Holo chat resume evidence."})
    chat = ChatRuntime(journal=journal, agent_runtime=agent)

    pending = chat.receive("read the file", thread_id="thread-resume")
    resumed = chat.receive("README.md", thread_id="thread-resume")
    state = chat.build_thread_state("thread-resume")

    assert resumed.route == "answer_pending_question"
    assert resumed.task_id == pending.task_id
    assert resumed.status == "completed"
    assert state.pending_question is None
    assert "chat resume evidence" in resumed.answer
    assert journal.records(task_id=pending.task_id, kind="resume")


def test_phase62_continue_after_completed_task_asks_for_clarification_not_resume():
    journal = JournalStore.in_memory()
    chat = ChatRuntime(journal=journal, agent_runtime=AgentRuntime(journal=journal))

    first = chat.receive("state your role", thread_id="thread-continue")
    continued = chat.receive("继续", thread_id="thread-continue")
    state = chat.build_thread_state("thread-continue")

    assert first.status == "completed"
    assert continued.route == "new_task"
    assert continued.status == "needs_user_input"
    assert continued.task_id != first.task_id
    assert state.pending_question is not None
    assert not journal.records(task_id=first.task_id, kind="resume")


def test_phase62_new_command_with_goal_starts_new_task():
    journal = JournalStore.in_memory()
    chat = ChatRuntime(journal=journal, agent_runtime=AgentRuntime(journal=journal))

    first = chat.receive("first task", thread_id="thread-new")
    second = chat.receive("/new second task", thread_id="thread-new")

    assert second.route == "command"
    assert second.task_id is not None
    assert second.task_id != first.task_id
    assert second.command_result == {"started_new_task": True}


def test_phase62_cancel_clears_active_task():
    journal = JournalStore.in_memory()
    chat = ChatRuntime(journal=journal, agent_runtime=AgentRuntime(journal=journal))

    chat.receive("task before cancel", thread_id="thread-cancel")
    canceled = chat.receive("/cancel", thread_id="thread-cancel")
    state = chat.build_thread_state("thread-cancel")

    assert canceled.status == "canceled"
    assert state.active_task_id is None
    assert state.pending_question is None


def test_phase62_status_command_does_not_clear_pending_question():
    journal = JournalStore.in_memory()
    chat = ChatRuntime(journal=journal, agent_runtime=AgentRuntime(journal=journal))

    pending = chat.receive("read the file", thread_id="thread-status")
    status = chat.receive("/status", thread_id="thread-status")
    state = chat.build_thread_state("thread-status")

    assert pending.status == "needs_user_input"
    assert status.status == "completed"
    assert state.pending_question is not None
    assert state.pending_question["task_id"] == pending.task_id


def test_phase62_summary_query_answers_from_journal_derived_summary():
    journal = JournalStore.in_memory()
    chat = ChatRuntime(journal=journal, agent_runtime=AgentRuntime(journal=journal))

    chat.receive("explain gradient explosion", thread_id="thread-summary")
    summary = chat.receive("刚刚我们说了什么", thread_id="thread-summary")

    assert summary.route == "summary"
    assert summary.status == "completed"
    assert "explain gradient explosion" in (summary.answer or "")
    assert summary.summary is not None


def test_phase62_thread_summary_includes_last_answer_and_pending_question():
    journal = JournalStore.in_memory()
    chat = ChatRuntime(journal=journal, agent_runtime=AgentRuntime(journal=journal))

    chat.receive("who are you", thread_id="thread-state")
    chat.receive("read the file", thread_id="thread-state")
    summary = chat.summarize_thread("thread-state")

    assert summary.last_answer_preview is not None
    assert "Direct answer: who are you" in summary.last_answer_preview
    assert summary.pending_question is not None
    assert summary.pending_question["question"]


def test_phase62_no_durable_memory_is_written():
    journal = JournalStore.in_memory()
    chat = ChatRuntime(journal=journal, agent_runtime=AgentRuntime(journal=journal))

    chat.receive("hello", thread_id="thread-memory")
    chat.receive("刚刚我们说了什么", thread_id="thread-memory")

    forbidden = {"memory_write", "memory_writeback", "durable_memory", "memory_commit"}
    assert not forbidden.intersection({record.kind for record in journal.records()})


def test_phase62_cli_chat_once_status_and_summary(tmp_path: Path):
    journal = tmp_path / "journal.jsonl"
    index = tmp_path / "journal.sqlite"

    once = _run_cli("--journal", str(journal), "--index", str(index), "chat", "--thread", "cli-thread", "--once", "hello cli")
    payload = json.loads(once.stdout)
    assert payload["status"] == "completed"

    status = _run_cli("--journal", str(journal), "--index", str(index), "chat-status", "cli-thread")
    status_payload = json.loads(status.stdout)
    assert status_payload["active_task_id"] is None
    assert status_payload["last_result_status"] == "completed"

    summary = _run_cli("--journal", str(journal), "--index", str(index), "chat-summary", "cli-thread")
    summary_payload = json.loads(summary.stdout)
    assert "hello cli" in summary_payload["recent_turns"][-1]["text_preview"]


def _run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "kernel_v3.cli", *args],
        cwd=Path(__file__).resolve().parents[1],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )
