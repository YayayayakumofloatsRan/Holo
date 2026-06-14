import io
import json
import subprocess
import sys
from pathlib import Path

from kernel_v3 import cli
from kernel_v3.agent import AgentRuntime
from kernel_v3.agent.contracts import AgentRuntimeResult
from kernel_v3.chat import ChatRuntime
from kernel_v3.chat.console import (
    apply_console_model_settings,
    handle_chat_line,
    handle_model_settings_command,
    public_chat_result_payload,
    render_chat_activity,
    render_chat_result,
)
from kernel_v3.chat.contracts import ChatRuntimeResult
from kernel_v3.chat.settings import ModelSettingsStore, setting_update_for_profile
from kernel_v3.context import ArtifactStore
from kernel_v3.journal import JournalStore
from kernel_v3.processors import (
    DEEPSEEK_V4_FLASH,
    DEEPSEEK_V4_PRO,
    FakeJsonProvider,
    ProcessorFabric,
    ProcessorRouter,
    deepseek_v4_router,
)
from kernel_v3.processors.testing import fake_fabric
from kernel_v3.research import ResearchCorpusStore, corpus_document_from_retrieval
from kernel_v3.retrieval.contracts import FetchedDocument, SearchGoal, SearchSource


def test_phase62_two_turns_share_thread_id():
    journal = JournalStore.in_memory()
    chat = ChatRuntime(journal=journal, agent_runtime=AgentRuntime(journal=journal))

    first = chat.receive("hello", thread_id="thread-a")
    second = chat.receive("what next", thread_id="thread-a")

    assert first.thread_id == "thread-a"
    assert second.thread_id == "thread-a"
    assert {record.data["thread_id"] for record in journal.records(kind="chat_turn")} == {"thread-a"}


def test_phase62_chat_journal_redacts_secret_like_turn_text_before_summary():
    secret_url = "https://example.test/report?access_token=chat-secret-token-1234567890"
    journal = JournalStore.in_memory()
    chat = ChatRuntime(journal=journal, agent_runtime=AgentRuntime(journal=journal))

    result = chat.receive(f"please inspect {secret_url}", thread_id="thread-secret")
    summary = chat.summarize_thread("thread-secret")

    assert result.thread_id == "thread-secret"
    turn = journal.records(kind="chat_turn")[0].data
    thread_summary = journal.records(kind="thread_summary")[-1].data
    assert turn["text"] == "[REDACTED:SECRET]"
    assert turn["redaction"]["journal_data"] == "secret_like_fields_redacted"
    assert summary.recent_turns[-1]["text_preview"] == "[REDACTED:SECRET]"
    encoded = json.dumps(
        {
            "journal": [record.to_dict() for record in journal.records()],
            "summary": summary.to_dict(),
            "thread_summary": thread_summary,
        },
        ensure_ascii=False,
    )
    assert "chat-secret-token" not in encoded
    assert "access_token" not in encoded


def test_phase62_chat_input_normalizes_backspace_and_lone_surrogates():
    journal = JournalStore.in_memory()
    chat = ChatRuntime(journal=journal, agent_runtime=AgentRuntime(journal=journal))

    result = chat.receive("为什么世界是这么设计的x\b？\udce6", thread_id="thread-input-normalize")

    turn = journal.records(kind="chat_turn")[0].data
    assert result.thread_id == "thread-input-normalize"
    assert turn["text"] == "为什么世界是这么设计的？?"


def test_phase62_model_settings_store_keeps_global_and_thread_overrides_separate(tmp_path: Path):
    store = ModelSettingsStore(global_path=tmp_path / "global-model.json", thread_root=tmp_path / "threads")

    default_planner = store.effective_settings("alpha")["routes"]["planner.propose"]
    assert default_planner["model"] == DEEPSEEK_V4_FLASH
    assert default_planner["thinking"] == "disabled"
    assert default_planner["model_locked"] is False
    assert default_planner["thinking_locked"] is False

    store.update_global(setting_update_for_profile("quality"))
    alpha_quality = store.effective_settings("alpha")["routes"]["planner.propose"]
    beta_quality = store.effective_settings("beta")["routes"]["planner.propose"]
    assert alpha_quality["model"] == DEEPSEEK_V4_PRO
    assert alpha_quality["thinking"] == "enabled"
    assert alpha_quality["model_locked"] is True
    assert alpha_quality["thinking_locked"] is True
    assert beta_quality["model"] == DEEPSEEK_V4_PRO

    store.update_thread("alpha", setting_update_for_profile("speed"))
    alpha_speed = store.effective_settings("alpha")["routes"]["planner.propose"]
    beta_still_quality = store.effective_settings("beta")["routes"]["planner.propose"]
    assert alpha_speed["model"] == DEEPSEEK_V4_FLASH
    assert alpha_speed["thinking"] == "disabled"
    assert beta_still_quality["model"] == DEEPSEEK_V4_PRO
    assert store.thread_path("alpha").exists()

    store.reset_thread("alpha")
    assert store.effective_settings("alpha")["routes"]["planner.propose"]["model"] == DEEPSEEK_V4_PRO


def test_phase62_console_model_settings_restore_router_baseline_between_threads(tmp_path: Path):
    journal = JournalStore.in_memory()
    router = deepseek_v4_router(profile="balanced", generation_mode="auto", latency_target="quality")
    fabric = ProcessorFabric(providers={}, router=router, journal=journal)
    chat = ChatRuntime(journal=journal, agent_runtime=AgentRuntime(journal=journal, processor_fabric=fabric))
    store = ModelSettingsStore(global_path=tmp_path / "global-model.json", thread_root=tmp_path / "threads")

    assert apply_console_model_settings(chat, "plain-thread", settings_store=store) is False
    plain_planner = router.route("planner.propose")
    assert plain_planner.model == DEEPSEEK_V4_FLASH
    assert plain_planner.parameters["latency_target"] == "quality"
    assert plain_planner.parameters["model_locked"] is False
    assert plain_planner.parameters["thinking_locked"] is False

    status, result = handle_model_settings_command(
        ["set", "planner", "model", "pro", "thinking", "on", "effort", "high", "target", "quality"],
        runtime=chat,
        thread_id="quality-thread",
        store=store,
        output_mode="json",
        color=False,
    )

    assert status == "ok"
    assert result["applied_to_live_router"] is True
    quality_planner = router.route("planner.propose")
    assert quality_planner.model == DEEPSEEK_V4_PRO
    assert quality_planner.parameters["thinking"] == "enabled"
    assert quality_planner.parameters["reasoning_effort"] == "high"
    assert quality_planner.parameters["model_locked"] is True
    assert quality_planner.parameters["thinking_locked"] is True

    assert apply_console_model_settings(chat, "plain-thread", settings_store=store) is False
    restored_planner = router.route("planner.propose")
    assert restored_planner.model == DEEPSEEK_V4_FLASH
    assert restored_planner.parameters["latency_target"] == "quality"
    assert restored_planner.parameters["model_locked"] is False
    assert restored_planner.parameters["thinking_locked"] is False


def test_phase62_ask_user_result_creates_pending_question():
    journal = JournalStore.in_memory()
    chat = _chat_with_semantic(journal, [_workspace_read_intake()])

    result = chat.receive("read the file", thread_id="thread-pending")
    state = chat.build_thread_state("thread-pending")

    assert result.status == "needs_user_input"
    assert result.pending_question is not None
    assert state.pending_question is not None
    assert state.pending_question["task_id"] == result.task_id
    assert "question" in state.pending_question


def test_phase62_next_user_answer_resumes_same_task_and_clears_pending_state():
    journal = JournalStore.in_memory()
    chat = _chat_with_semantic(
        journal,
        [_workspace_read_intake(), _workspace_read_intake()],
        workspace_files={"README.md": "Holo chat resume evidence."},
    )

    pending = chat.receive("read the file", thread_id="thread-resume")
    resumed = chat.receive("README.md", thread_id="thread-resume")
    state = chat.build_thread_state("thread-resume")

    assert resumed.route == "answer_pending_question"
    assert resumed.task_id == pending.task_id
    assert resumed.status == "completed"
    assert state.pending_question is None
    assert "chat resume evidence" in resumed.answer
    assert journal.records(task_id=pending.task_id, kind="resume")


def test_phase62_pending_answer_passes_thread_working_context_to_agent_resume():
    journal = JournalStore.in_memory()
    pending_chat = _chat_with_semantic(journal, [_workspace_read_intake()])
    pending = pending_chat.receive("read the file", thread_id="thread-context")
    agent = CapturingAgentRuntime()
    chat = ChatRuntime(journal=journal, agent_runtime=agent)  # type: ignore[arg-type]

    resumed = chat.receive("README.md", thread_id="thread-context")

    assert resumed.route == "answer_pending_question"
    assert agent.resume_calls
    metadata = agent.resume_calls[-1]["execution_metadata"]
    working = metadata["thread_working_context"]
    assert working["route"] == "answer_pending_question"
    assert working["resume_semantics"]["same_task"] is True
    assert working["pending_question"]["task_id"] == pending.task_id
    assert working["original_task"]["input_text_preview"] == "read the file"
    assert any(item["text_preview"] == "README.md" for item in working["recent_turns"])
    assert any(item["kind"] == "observation" and item["status"] == "needs_user_input" for item in working["recent_task_trace"])


def test_phase62_semantic_intake_prompt_includes_thread_working_context():
    journal = JournalStore.in_memory()
    provider = CapturingFakeJsonProvider(
        {
            "semantic.intake": [_workspace_read_intake(), _direct_intake()],
        }
    )
    fabric = ProcessorFabric(
        providers={"fake_json": provider},
        router=ProcessorRouter(default_provider="fake_json", default_model="fake-json"),
        journal=journal,
    )
    agent = AgentRuntime(journal=journal, processor_fabric=fabric)
    chat = ChatRuntime(journal=journal, agent_runtime=agent, semantic_mode="model")

    pending = chat.receive("read the file", thread_id="thread-semantic-context")
    chat.receive("README.md", thread_id="thread-semantic-context")

    assert pending.status == "needs_user_input"
    prompt = json.loads(provider.last_prompt)
    working = prompt["runtime_context"]["thread_working_context"]
    assert working["route"] == "answer_pending_question"
    assert working["pending_question"]["task_id"] == pending.task_id
    assert working["original_task"]["input_text_preview"] == "read the file"
    assert any(turn["text_preview"] == "README.md" for turn in working["recent_turns"])


def test_phase62_thread_working_context_includes_recent_conversation_results():
    journal = JournalStore.in_memory()
    provider = CapturingFakeJsonProvider(
        {
            "semantic.intake": [_direct_intake(), _direct_intake()],
        }
    )
    fabric = ProcessorFabric(
        providers={"fake_json": provider},
        router=ProcessorRouter(default_provider="fake_json", default_model="fake-json"),
        journal=journal,
    )
    agent = AgentRuntime(journal=journal, processor_fabric=fabric)
    chat = ChatRuntime(journal=journal, agent_runtime=agent, semantic_mode="model")

    chat.receive("你能做什么？", thread_id="thread-dialogue-context")
    chat.receive("接着说", thread_id="thread-dialogue-context")

    prompt = json.loads(provider.last_prompt)
    working = prompt["runtime_context"]["thread_working_context"]
    dialogue = working["recent_conversation"]
    assert any(item["kind"] == "chat_turn" and item["text_preview"] == "你能做什么？" for item in dialogue)
    assert any(item["kind"] == "chat_agent_result" and item["role"] == "assistant" for item in dialogue)
    assert any(item["kind"] == "chat_turn" and item["text_preview"] == "接着说" for item in dialogue)


def test_phase62_pending_answer_can_change_resume_from_retrieval_to_direct_mode():
    journal = JournalStore.in_memory()
    journal.append(
        task_id="task-existing",
        run_id="run-1",
        step_id=None,
        kind="task",
        data={
            "task_id": "task-existing",
            "status": "running",
            "input_text": "查一下 Apple Inc 的基本面信息",
            "thread_id": "thread-mode",
        },
        state_delta={"status": "running"},
    )
    fabric = fake_fabric({"semantic.intake": _direct_intake()}, journal=journal)
    runtime = AgentRuntime(journal=journal, processor_fabric=fabric)

    result = runtime.resume(
        "task-existing",
        "好的，告诉我你知道的东西",
        thread_id="thread-mode",
        mode="retrieval_answer",
        semantic_mode="model",
        execution_metadata={
            "thread_working_context": {
                "route": "answer_pending_question",
                "pending_question": {"task_id": "task-existing"},
                "resume_semantics": {"same_task": True},
                "original_task": {"input_text_preview": "查一下 Apple Inc 的基本面信息"},
            }
        },
    )

    assert result.status == "completed"
    assert result.mode == "direct_answer"
    assert result.final_answer is not None
    assert not [record for record in journal.records(task_id="task-existing", kind="action") if record.data.get("name") == "retrieval.run"]


def test_phase62_pending_question_does_not_swallow_model_routed_new_task():
    journal = JournalStore.in_memory()
    pending_chat = _chat_with_semantic(journal, [_workspace_read_intake()])
    pending = pending_chat.receive("read the file", thread_id="thread-pending-new")
    fabric = fake_fabric(
        {
            "chat.route": {
                "route": "new_task",
                "command": None,
                "target_task_id": None,
                "confidence": 0.94,
                "reasons": ["fresh_request_despite_pending_question"],
            },
            "semantic.intake": _direct_intake(),
        },
        journal=journal,
    )
    chat = ChatRuntime(
        journal=journal,
        agent_runtime=AgentRuntime(journal=journal, processor_fabric=fabric),
        semantic_mode="model",
        turn_router_mode="model",
    )

    fresh = chat.receive("去检索一下 apple inc 的基本面信息", thread_id="thread-pending-new")

    assert pending.status == "needs_user_input"
    assert fresh.route == "new_task"
    assert fresh.task_id != pending.task_id
    assert not journal.records(task_id=pending.task_id, kind="resume")
    route = journal.records(kind="chat_routing_decision")[-1].data
    assert route["route"] == "new_task"
    assert "fresh_request_despite_pending_question" in route["reasons"]


def test_phase62_broad_pending_clarification_does_not_swallow_operational_goal_even_if_model_misroutes():
    journal = JournalStore.in_memory()
    pending_chat = _chat_with_semantic(journal, [_clarify_intake()])
    pending = pending_chat.receive("我不明白", thread_id="thread-pending-operational")
    fabric = fake_fabric(
        {
            "chat.route": {
                "route": "answer_pending_question",
                "command": None,
                "target_task_id": pending.task_id,
                "confidence": 0.91,
                "reasons": ["model_thought_this_answered_the_pending_question"],
                "route_relation": {
                    "same_task": False,
                    "is_standalone_goal": True,
                    "relation_reason": "The turn is a fresh operational goal rather than an answer to the old broad clarification.",
                },
            },
            "semantic.intake": _direct_intake(),
        },
        journal=journal,
    )
    chat = ChatRuntime(
        journal=journal,
        agent_runtime=AgentRuntime(journal=journal, processor_fabric=fabric),
        semantic_mode="model",
        turn_router_mode="model",
    )

    fresh = chat.receive("你能去搜一下 apple inc 的基本面吗", thread_id="thread-pending-operational")

    assert pending.status == "needs_user_input"
    assert fresh.route == "new_task"
    assert fresh.task_id != pending.task_id
    assert not journal.records(task_id=pending.task_id, kind="resume")
    route = journal.records(kind="chat_routing_decision")[-1].data
    assert route["route"] == "new_task"
    assert "model_relation_overrode_pending_question" in route["reasons"]


def test_phase62_continue_after_completed_task_asks_for_clarification_not_resume():
    journal = JournalStore.in_memory()
    chat = ChatRuntime(journal=journal, agent_runtime=AgentRuntime(journal=journal))

    first = chat.receive("state your role", thread_id="thread-continue")
    fabric = fake_fabric(
        {
            "chat.route": {
                "route": "continue_plan",
                "command": None,
                "target_task_id": None,
                "confidence": 0.94,
                "reasons": ["semantic_continuation_request"],
            }
        },
        journal=journal,
    )
    chat = ChatRuntime(
        journal=journal,
        agent_runtime=AgentRuntime(journal=journal, processor_fabric=fabric),
        turn_router_mode="model",
    )
    continued = chat.receive("pick up from there somehow", thread_id="thread-continue")
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


def test_phase62_interrupt_alias_clears_active_task():
    journal = JournalStore.in_memory()
    chat = ChatRuntime(journal=journal, agent_runtime=AgentRuntime(journal=journal))

    chat.receive("task before interrupt", thread_id="thread-interrupt")
    interrupted = chat.receive("/interrupt", thread_id="thread-interrupt")
    state = chat.build_thread_state("thread-interrupt")

    assert interrupted.status == "canceled"
    assert interrupted.command_result is not None
    assert interrupted.command_result["name"] == "/interrupt"
    assert "active_task_cleared" in interrupted.command_result["result"]
    assert interrupted.task_id is None
    assert "interrupted" in (interrupted.answer or "")
    assert state.active_task_id is None
    assert state.pending_question is None


def test_phase62_status_command_does_not_clear_pending_question():
    journal = JournalStore.in_memory()
    chat = _chat_with_semantic(journal, [_workspace_read_intake()])

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
    fabric = fake_fabric(
        {
            "chat.route": {
                "route": "summary",
                "command": None,
                "target_task_id": None,
                "confidence": 0.96,
                "reasons": ["semantic_recap_request"],
            }
        },
        journal=journal,
    )
    chat = ChatRuntime(
        journal=journal,
        agent_runtime=AgentRuntime(journal=journal, processor_fabric=fabric),
        turn_router_mode="model",
    )
    summary = chat.receive("give me the thread so far in your own words", thread_id="thread-summary")

    assert summary.route == "summary"
    assert summary.status == "completed"
    assert "explain gradient explosion" in (summary.answer or "")
    assert summary.summary is not None
    assert journal.records(kind="processor_result")[-1].data["task_type"] == "chat.route"


def test_phase62_model_turn_router_cannot_execute_chat_commands():
    journal = JournalStore.in_memory()
    fabric = fake_fabric(
        {
            "chat.route": {
                "route": "command",
                "command": "/memory approve proposal-1",
                "target_task_id": None,
                "confidence": 0.99,
                "reasons": ["unsafe_model_command_attempt"],
            }
        },
        journal=journal,
    )
    chat = ChatRuntime(
        journal=journal,
        agent_runtime=AgentRuntime(journal=journal, processor_fabric=fabric),
        turn_router_mode="model",
    )

    result = chat.receive("approve every pending memory item", thread_id="thread-model-command")

    assert result.route == "new_task"
    assert result.status == "completed"
    assert not journal.records(kind="chat_command")


def test_phase62_thread_summary_includes_last_answer_and_pending_question():
    journal = JournalStore.in_memory()
    chat = _chat_with_semantic(journal, [_direct_intake(), _workspace_read_intake()])

    chat.receive("who are you", thread_id="thread-state")
    chat.receive("read the file", thread_id="thread-state")
    summary = chat.summarize_thread("thread-state")

    assert summary.last_answer_preview is not None
    assert "离线 host fallback" in summary.last_answer_preview
    assert "Direct answer:" not in summary.last_answer_preview
    assert summary.pending_question is not None
    assert summary.pending_question["question"]


def test_phase62_summary_route_is_thread_level_and_does_not_reprint_pending_prompt():
    journal = JournalStore.in_memory()
    pending_chat = _chat_with_semantic(journal, [_workspace_read_intake()])
    pending = pending_chat.receive("read the file", thread_id="thread-summary-route")
    fabric = fake_fabric(
        {
            "chat.route": {
                "route": "summary",
                "command": None,
                "target_task_id": None,
                "confidence": 0.96,
                "reasons": ["user_requested_conversation_recap"],
            },
        },
        journal=journal,
    )
    chat = ChatRuntime(
        journal=journal,
        agent_runtime=AgentRuntime(journal=journal, processor_fabric=fabric),
        turn_router_mode="model",
    )

    result = chat.receive("我们之前说了什么？", thread_id="thread-summary-route")
    rendered = render_chat_result(result, color=False)

    assert pending.status == "needs_user_input"
    assert result.route == "summary"
    assert result.task_id is None
    assert result.pending_question is None
    assert "待补充:" in (result.answer or "")
    assert "needs input:" not in rendered


def test_phase62_summary_route_is_model_owned_not_phrase_guarded():
    journal = JournalStore.in_memory()
    fabric = fake_fabric(
        {
            "chat.route": {
                "route": "summary",
                "command": None,
                "target_task_id": None,
                "confidence": 0.88,
                "reasons": ["model_misread_confusion_as_recap"],
            },
            "semantic.intake": _direct_intake(),
        },
        journal=journal,
    )
    chat = ChatRuntime(
        journal=journal,
        agent_runtime=AgentRuntime(journal=journal, processor_fabric=fabric),
        semantic_mode="model",
        turn_router_mode="model",
    )

    result = chat.receive("我不明白", thread_id="thread-summary-guard")

    assert result.route == "summary"
    route = journal.records(kind="chat_routing_decision")[-1].data
    assert "model_misread_confusion_as_recap" in route["reasons"]


def test_phase62_specific_thread_memory_question_follows_model_route():
    journal = JournalStore.in_memory()
    fabric = fake_fabric(
        {
            "chat.route": {
                "route": "new_task",
                "command": None,
                "target_task_id": None,
                "confidence": 0.88,
                "reasons": ["model_classified_specific_memory_question_as_task"],
            },
            "semantic.intake": _direct_intake(),
        },
        journal=journal,
    )
    chat = ChatRuntime(
        journal=journal,
        agent_runtime=AgentRuntime(journal=journal, processor_fabric=fabric),
        semantic_mode="model",
        turn_router_mode="model",
    )

    result = chat.receive("刚才我说我正在审查什么？", thread_id="thread-specific-memory")

    assert result.route == "new_task"
    route = journal.records(kind="chat_routing_decision")[-1].data
    assert "model_classified_specific_memory_question_as_task" in route["reasons"]


def test_phase62_no_durable_memory_is_written():
    journal = JournalStore.in_memory()
    chat = ChatRuntime(journal=journal, agent_runtime=AgentRuntime(journal=journal))

    chat.receive("hello", thread_id="thread-memory")
    chat.receive("/summary", thread_id="thread-memory")

    forbidden = {"memory_write", "memory_writeback", "durable_memory", "memory_commit"}
    assert not forbidden.intersection({record.kind for record in journal.records()})


def test_phase62_chat_passes_model_semantic_mode_to_agent_runtime():
    journal = JournalStore.in_memory()
    fabric = fake_fabric(
        {
            "semantic.intake": {
                "primary_intent": "retrieval_research",
                "suggested_mode": "retrieval_answer",
                "compound": False,
                "requires_clarification": False,
                "intents": [
                    {
                        "kind": "retrieval_research",
                        "text": "research current external evidence",
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
        },
        journal=journal,
    )
    artifacts = ArtifactStore.in_memory()
    agent = AgentRuntime(
        journal=journal,
        processor_fabric=fabric,
        artifact_store=artifacts,
        research_corpus_store=_corpus_with_document(artifacts, query_text="current external evidence"),
    )
    chat = ChatRuntime(journal=journal, agent_runtime=agent, semantic_mode="model")

    result = chat.receive("an unseen request that needs current evidence", thread_id="thread-model-chat")

    assert result.status == "completed"
    assert result.final_answer is not None
    assert result.final_answer["citation_refs"]
    assert journal.records(task_id=result.task_id, kind="processor_result")[0].data["task_type"] == "semantic.intake"


def test_phase62_cli_chat_once_status_and_summary(tmp_path: Path):
    journal = tmp_path / "journal.jsonl"
    index = tmp_path / "journal.sqlite"

    once = _run_cli(
        "--journal",
        str(journal),
        "--index",
        str(index),
        "chat",
        "--offline",
        "--thread",
        "cli-thread",
        "--once",
        "hello cli",
    )
    payload = json.loads(once.stdout)
    assert payload["status"] == "completed"

    status = _run_cli("--journal", str(journal), "--index", str(index), "chat-status", "cli-thread")
    status_payload = json.loads(status.stdout)
    assert status_payload["active_task_id"] is None
    assert status_payload["last_result_status"] == "completed"

    summary = _run_cli("--journal", str(journal), "--index", str(index), "chat-summary", "cli-thread")
    summary_payload = json.loads(summary.stdout)
    assert "hello cli" in summary_payload["recent_turns"][-1]["text_preview"]


def test_phase62_root_holo_v3_launcher_executes_cli():
    root = Path(__file__).resolve().parents[1]

    result = subprocess.run(
        [str(root / "holo-v3"), "--help"],
        cwd=root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )

    assert "usage: holo-v3" in result.stdout
    assert "chat" in result.stdout


def test_phase62_bare_holo_v3_defaults_to_live_chat_and_errors_when_not_enabled(capsys, monkeypatch):
    monkeypatch.delenv("HOLO_V3_LIVE_MODEL", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

    status = cli.main([])

    output = capsys.readouterr().out
    assert status == 1
    assert "blocked" in output
    assert "live_model_not_enabled" in output
    assert "DEEPSEEK_API_KEY" in output


def test_phase62_cli_chat_pipe_mode_stays_json(tmp_path: Path, capsys, monkeypatch):
    journal = tmp_path / "journal.jsonl"
    index = tmp_path / "journal.sqlite"
    monkeypatch.setattr(sys, "stdin", io.StringIO("hello through pipe\n"))

    status = cli.main(["--journal", str(journal), "--index", str(index), "chat", "--offline", "--thread", "cli-pipe"])

    output = capsys.readouterr().out.strip()
    payload = json.loads(output)
    assert status == 0
    assert payload["thread_id"] == "cli-pipe"
    assert payload["status"] == "completed"
    assert "\x1b[" not in output


def test_phase62_cli_chat_human_mode_can_switch_threads(tmp_path: Path, capsys, monkeypatch):
    journal = tmp_path / "journal.jsonl"
    index = tmp_path / "journal.sqlite"
    monkeypatch.setattr(
        sys,
        "stdin",
        io.StringIO("/thread switch cli-beta\nhello beta\n/threads\n/quit\n"),
    )

    status = cli.main(
        [
            "--journal",
            str(journal),
            "--index",
            str(index),
            "chat",
            "--offline",
            "--thread",
            "cli-alpha",
            "--output",
            "human",
            "--color",
            "always",
        ]
    )

    output = capsys.readouterr().out
    thread_ids = {
        record.data["thread_id"]
        for record in JournalStore(journal, index_path=index).records(kind="chat_turn")
    }
    assert status == 0
    assert "\x1b[" in output
    assert "thread: cli-beta" in output
    assert "cli-beta" in output
    assert thread_ids == {"cli-beta"}


def test_phase62_cli_chat_can_create_empty_thread_and_list_it(tmp_path: Path, capsys, monkeypatch):
    journal = tmp_path / "journal.jsonl"
    index = tmp_path / "journal.sqlite"
    monkeypatch.setattr(sys, "stdin", io.StringIO("/thread new cli-empty\n/thread list\n/quit\n"))

    status = cli.main(
        [
            "--journal",
            str(journal),
            "--index",
            str(index),
            "chat",
            "--offline",
            "--thread",
            "cli-alpha",
            "--output",
            "human",
        ]
    )

    output = capsys.readouterr().out
    store = JournalStore(journal, index_path=index)
    events = store.records(kind="chat_thread_event")
    turns = store.records(kind="chat_turn")
    assert status == 0
    assert "thread: cli-empty" in output
    assert "created: true" in output
    assert "* cli-empty turns=0 status=None" in output
    assert len(events) == 1
    assert events[0].data["thread_id"] == "cli-empty"
    assert events[0].data["action"] == "created"
    assert events[0].data["created"] is True
    assert turns == []


def test_phase62_cli_chat_history_displays_current_thread_records(tmp_path: Path, capsys, monkeypatch):
    journal = tmp_path / "journal.jsonl"
    index = tmp_path / "journal.sqlite"
    monkeypatch.setattr(sys, "stdin", io.StringIO("hello history\n/history 4\n/quit\n"))

    status = cli.main(
        [
            "--journal",
            str(journal),
            "--index",
            str(index),
            "chat",
            "--offline",
            "--thread",
            "cli-history",
            "--output",
            "human",
            "--color",
            "never",
        ]
    )

    output = capsys.readouterr().out
    assert status == 0
    assert "/history ok" in output
    assert "thread: cli-history" in output
    assert "user" in output
    assert "assistant" in output
    assert "hello history" in output
    assert "status=completed route=new_task" in output


def test_phase62_cli_chat_model_mode_is_live_gated(tmp_path: Path, capsys, monkeypatch):
    monkeypatch.delenv("HOLO_V3_LIVE_MODEL", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    journal = tmp_path / "journal.jsonl"
    index = tmp_path / "journal.sqlite"

    status = cli.main(
        [
            "--journal",
            str(journal),
            "--index",
            str(index),
            "chat",
            "--thread",
            "cli-model-thread",
            "--once",
            "hello",
            "--semantic-intake",
            "model",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert status == 1
    assert payload == {"reason": "live_model_not_enabled", "status": "blocked"}


def test_phase62_cli_chat_defaults_to_live_model(tmp_path: Path, capsys, monkeypatch):
    monkeypatch.delenv("HOLO_V3_LIVE_MODEL", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    journal = tmp_path / "journal.jsonl"
    index = tmp_path / "journal.sqlite"

    status = cli.main(
        [
            "--journal",
            str(journal),
            "--index",
            str(index),
            "chat",
            "--thread",
            "cli-default-live-thread",
            "--once",
            "hello",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert status == 1
    assert payload == {"reason": "live_model_not_enabled", "status": "blocked"}
    assert JournalStore(journal, index_path=index).records() == []


def test_phase62_cli_chat_online_mode_is_live_gated(tmp_path: Path, capsys, monkeypatch):
    monkeypatch.delenv("HOLO_V3_LIVE_MODEL", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    journal = tmp_path / "journal.jsonl"
    index = tmp_path / "journal.sqlite"

    status = cli.main(
        [
            "--journal",
            str(journal),
            "--index",
            str(index),
            "chat",
            "--thread",
            "cli-online-thread",
            "--once",
            "hello",
            "--online",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert status == 1
    assert payload == {"reason": "live_model_not_enabled", "status": "blocked"}
    assert JournalStore(journal, index_path=index).records() == []


def test_phase62_cli_chat_deepseek_key_enables_default_live_without_holo_gate(tmp_path: Path, capsys, monkeypatch):
    monkeypatch.delenv("HOLO_V3_LIVE_MODEL", raising=False)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key-present")
    monkeypatch.setattr(
        cli,
        "_live_processor_fabric",
        lambda _provider, journal, **_kwargs: fake_fabric(
            {
                "chat.route": {
                    "route": "new_task",
                    "command": None,
                    "target_task_id": None,
                    "confidence": 0.95,
                    "reasons": ["key_enabled_route"],
                },
                "semantic.intake": {
                    "primary_intent": "direct_answer",
                    "suggested_mode": "direct_answer",
                    "compound": False,
                    "requires_clarification": False,
                    "intents": [
                        {
                            "kind": "direct_answer",
                            "text": "hello",
                            "sequence_index": 1,
                            "required_capabilities": [],
                            "risk": "none",
                            "status": "ready",
                            "metadata": {},
                        }
                    ],
                    "blocked_capabilities": [],
                    "warnings": [],
                    "response_hint": None,
                    "clarification_question": None,
                },
                "planner.propose": {
                    "action_id": "act-key-enabled-direct",
                    "kind": "respond",
                    "name": None,
                    "description": "key-enabled default live answer",
                    "payload": {"text": "key-enabled-live-response"},
                    "score": 0.95,
                    "reasons": ["key_enabled_live"],
                    "side_effect_class": "none",
                },
                "evaluator.assess": {
                    "status": "final_answer_ready",
                    "answer": None,
                    "stop_reason": "completed",
                    "missing_evidence": [],
                },
            },
            journal=journal,
        ),
    )
    journal = tmp_path / "journal.jsonl"
    index = tmp_path / "journal.sqlite"

    status = cli.main(
        [
            "--journal",
            str(journal),
            "--index",
            str(index),
            "chat",
            "--thread",
            "cli-key-live-thread",
            "--once",
            "hello",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert status == 0
    assert payload["answer"] == "key-enabled-live-response"


def test_phase62_cli_agent_defaults_to_live_model(tmp_path: Path, capsys, monkeypatch):
    monkeypatch.delenv("HOLO_V3_LIVE_MODEL", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    journal = tmp_path / "journal.jsonl"
    index = tmp_path / "journal.sqlite"

    status = cli.main(
        [
            "--journal",
            str(journal),
            "--index",
            str(index),
            "agent",
            "hello",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert status == 1
    assert payload == {"reason": "live_model_not_enabled", "status": "blocked"}
    assert JournalStore(journal, index_path=index).records() == []


def test_phase62_cli_agent_deepseek_key_enables_online_without_holo_gate(tmp_path: Path, capsys, monkeypatch):
    monkeypatch.delenv("HOLO_V3_LIVE_MODEL", raising=False)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key-present")
    monkeypatch.setattr(
        cli,
        "_live_processor_fabric",
        lambda _provider, journal, **_kwargs: fake_fabric(
            {
                "semantic.intake": {
                    "primary_intent": "direct_answer",
                    "suggested_mode": "direct_answer",
                    "compound": False,
                    "requires_clarification": False,
                    "intents": [
                        {
                            "kind": "direct_answer",
                            "text": "hello",
                            "sequence_index": 1,
                            "required_capabilities": [],
                            "risk": "none",
                            "status": "ready",
                            "metadata": {},
                        }
                    ],
                    "blocked_capabilities": [],
                    "warnings": [],
                    "response_hint": None,
                    "clarification_question": None,
                },
                "planner.propose": {
                    "action_id": "act-agent-key-live",
                    "kind": "respond",
                    "name": None,
                    "description": "key-enabled agent online answer",
                    "payload": {"text": "agent-key-enabled-live-response"},
                    "score": 0.95,
                    "reasons": ["key_enabled_agent_live"],
                    "side_effect_class": "none",
                },
                "evaluator.assess": {
                    "status": "final_answer_ready",
                    "answer": None,
                    "stop_reason": "completed",
                    "missing_evidence": [],
                },
            },
            journal=journal,
        ),
    )
    journal = tmp_path / "journal.jsonl"
    index = tmp_path / "journal.sqlite"

    status = cli.main(
        [
            "--journal",
            str(journal),
            "--index",
            str(index),
            "agent",
            "hello",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert status == 0
    assert payload["status"] == "completed"
    assert payload["final_answer"]["answer"] == "agent-key-enabled-live-response"


def test_phase62_cli_chat_online_mode_uses_model_backed_processors(tmp_path: Path, capsys, monkeypatch):
    monkeypatch.setenv("HOLO_V3_LIVE_MODEL", "1")
    model_action_text = "online-model-smoke-response"
    monkeypatch.setattr(
        cli,
        "_live_processor_fabric",
        lambda _provider, journal, **_kwargs: fake_fabric(
            {
                "chat.route": {
                    "route": "new_task",
                    "command": None,
                    "target_task_id": None,
                    "confidence": 0.95,
                    "reasons": ["online_model_route"],
                },
                "semantic.intake": {
                    "primary_intent": "roleplay",
                    "suggested_mode": "direct_answer",
                    "compound": False,
                    "requires_clarification": False,
                    "intents": [
                        {
                            "kind": "roleplay",
                            "text": "扮演一个初出茅庐的律师",
                            "sequence_index": 1,
                            "required_capabilities": [],
                            "risk": "none",
                            "status": "ready",
                            "metadata": {},
                        }
                    ],
                    "blocked_capabilities": [],
                    "warnings": [],
                    "response_hint": None,
                    "clarification_question": None,
                },
                "planner.propose": {
                    "action_id": "act-online-direct",
                    "kind": "respond",
                    "name": None,
                    "description": "online model direct answer",
                    "payload": {"text": model_action_text},
                    "score": 0.95,
                    "reasons": ["online_model_direct_answer"],
                    "side_effect_class": "none",
                },
                "evaluator.assess": {
                    "status": "final_answer_ready",
                    "answer": None,
                    "stop_reason": "completed",
                    "missing_evidence": [],
                },
            },
            journal=journal,
        ),
    )
    journal = tmp_path / "journal.jsonl"
    index = tmp_path / "journal.sqlite"

    status = cli.main(
        [
            "--journal",
            str(journal),
            "--index",
            str(index),
            "chat",
            "--thread",
            "cli-online-thread",
            "--once",
            "扮演一个初出茅庐的律师，你会怎么做",
            "--online",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    records = JournalStore(journal, index_path=index).records(task_id=payload["task_id"])
    task_types = [
        record.data["task_type"]
        for record in records
        if record.kind == "processor_request" and isinstance(record.data, dict)
    ]
    actions = [record.data for record in records if record.kind == "action" and isinstance(record.data, dict)]
    assert status == 0
    assert payload["status"] == "completed"
    assert actions[-1]["reasons"] == ["online_model_direct_answer"]
    assert payload["answer"] == actions[-1]["payload"]["text"]
    assert "离线 host fallback" not in payload["answer"]
    assert {"semantic.intake", "planner.propose", "evaluator.assess"}.issubset(set(task_types))
    assert any(record.kind == "processor_request" and record.data.get("task_type") == "chat.route" for record in JournalStore(journal, index_path=index).records())


def test_phase62_successful_semantic_response_is_not_converted_to_generic_pending_input(tmp_path: Path, capsys, monkeypatch):
    monkeypatch.setenv("HOLO_V3_LIVE_MODEL", "1")
    response_text = "语言的边界确实会影响思想的边界，但这不等于沉默本身没有意义。"
    monkeypatch.setattr(
        cli,
        "_live_processor_fabric",
        lambda _provider, journal, **_kwargs: fake_fabric(
            {
                "chat.route": {
                    "route": "new_task",
                    "command": None,
                    "target_task_id": None,
                    "confidence": 0.95,
                    "reasons": ["semantic_discussion"],
                },
                "semantic.intake": {
                    "primary_intent": "philosophical_discussion",
                    "suggested_mode": "semantic_answer",
                    "compound": False,
                    "requires_clarification": False,
                    "intents": [
                        {
                            "kind": "philosophical_discussion",
                            "text": "语言极限与维特根斯坦",
                            "sequence_index": 1,
                            "required_capabilities": [],
                            "risk": "none",
                            "status": "ready",
                            "metadata": {},
                        }
                    ],
                    "blocked_capabilities": [],
                    "warnings": [],
                    "response_hint": None,
                    "clarification_question": None,
                },
                "planner.propose": {
                    "action_id": "act-philosophy-response",
                    "kind": "respond",
                    "name": None,
                    "description": "continue philosophical discussion",
                    "payload": {"text": response_text},
                    "score": 0.92,
                    "reasons": ["semantic answer is available"],
                    "side_effect_class": "none",
                },
                "evaluator.assess": {
                    "status": "needs_user_input",
                    "answer": None,
                    "stop_reason": "needs_user_input",
                    "missing_evidence": ["clarification_required"],
                },
            },
            journal=journal,
        ),
    )
    journal = tmp_path / "journal.jsonl"
    index = tmp_path / "journal.sqlite"

    status = cli.main(
        [
            "--journal",
            str(journal),
            "--index",
            str(index),
            "chat",
            "--thread",
            "cli-philosophy-thread",
            "--once",
            "语言是存在着它固有的极限的",
            "--online",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    decisions = JournalStore(journal, index_path=index).records(task_id=payload["task_id"], kind="termination_decision")
    assert status == 0
    assert payload["status"] == "completed"
    assert payload["pending_question"] is None
    assert payload["answer"] == response_text
    assert decisions[-1].data["decision"] == "final_answer"
    assert decisions[-1].data["reason"] == "successful_response_overrode_spurious_user_input"


def test_phase62_human_console_activity_renders_processor_action_and_termination():
    journal = JournalStore.in_memory()
    result = AgentRuntime(journal=journal).run("explain Holo briefly", mode="direct")

    activity = render_chat_activity(journal.records(task_id=result.task_id), color=False)

    assert "steps" in activity
    assert "[action] action respond" in activity
    assert "[policy] policy allowed=True" in activity
    assert "[observe] observation source=respond" in activity
    assert "[reason] termination decision=final_answer" in activity
    assert "[final] final answer confidence=" in activity
    assert "action respond" in activity
    assert "policy allowed=True" in activity
    assert "observation source=respond" in activity
    assert "termination decision=final_answer" in activity
    assert "final answer confidence=" in activity


def test_phase62_human_console_activity_colors_public_agent_phases():
    journal = JournalStore.in_memory()
    for kind, data in [
        ("processor_request", {"task_type": "planner.propose", "provider": "deepseek", "model": "deepseek-v4-pro"}),
        ("action", {"name": "retrieval.run", "side_effect_class": "network", "reasons": ["needs evidence"]}),
        ("policy_decision", {"allowed": True, "reason": "allowed"}),
        ("observation", {"source": "tool:retrieval.run", "status": "ok"}),
        ("retrieval_search_attempt", {"query": "DeepSeek API", "status": "ok", "sources": [{"source_id": "src-1"}]}),
        ("retrieval_evidence", {"evidence_id": "ev-1", "score": 0.91, "source_id": "src-1"}),
        ("termination_decision", {"decision": "final_answer", "reason": "evidence_sufficient"}),
        ("agent_final_answer", {"confidence": 0.87}),
    ]:
        journal.append(task_id="task-color", run_id="run-1", step_id=None, kind=kind, data=data)

    activity = render_chat_activity(journal.records(task_id="task-color"), color=True)

    assert "\033[" in activity
    assert "\033[1;37m[model] model request planner.propose" in activity
    assert "  \033[2m·\033[0m \033[38;5;172m[tool] action retrieval.run" in activity
    assert "    \033[2m·\033[0m \033[32m[retrieval] retrieval search query=DeepSeek API" in activity
    assert "[model]" in activity
    assert "[tool]" in activity
    assert "[policy]" in activity
    assert "[retrieval]" in activity
    assert "[evidence]" in activity
    assert "[reason]" in activity
    assert "[final]" in activity


def test_phase62_human_console_result_uses_light_answer_text():
    payload = ChatRuntimeResult(
        status="completed",
        thread_id="thread-answer-color",
        turn_id="turn-answer-color",
        route="new_task",
        task_id="task-answer-color",
        run_id="run-1",
        answer="这是最终回答。",
        final_answer=None,
        failure_report=None,
        pending_question=None,
        command_result=None,
        summary=None,
        trace_refs=["ledger-1"],
    )

    rendered = render_chat_result(payload, color=True)

    assert "\033[1;32m[answer]\033[0m" in rendered
    assert "\033[97m这是最终回答。\033[0m" in rendered


def test_phase62_human_console_failure_report_renders_actionable_details():
    payload = ChatRuntimeResult(
        status="failed",
        thread_id="thread-failure",
        turn_id="turn-failure",
        route="new_task",
        task_id="task-failure",
        run_id="run-1",
        answer=None,
        final_answer=None,
        failure_report={
            "reason": "planned_retrieval_subgoals_incomplete",
            "attempted_actions": ["retrieval.run", "retrieval.run"],
            "attempted_sources": ["https://example.test/source"],
            "missing_evidence": ["sufficient_retrieval_evidence", "retrieval_subgoal:goal-1"],
            "last_observations": [],
            "user_help_needed": False,
            "next_possible_action": "refine_failed_retrieval_subgoals",
            "task_id": "task-failure",
            "run_id": "run-1",
            "trace_refs": ["ledger-1"],
        },
        pending_question=None,
        command_result=None,
        summary=None,
        trace_refs=["ledger-1"],
    )

    rendered = render_chat_result(payload, color=False)

    assert "[answer] 我这次没有完成目标" in rendered
    assert "failure: planned_retrieval_subgoals_incomplete" in rendered
    assert "missing: [sufficient_retrieval_evidence, retrieval_subgoal:goal-1]" in rendered
    assert "attempted: [retrieval.run, retrieval.run]" in rendered
    assert "next: refine_failed_retrieval_subgoals" in rendered


def test_phase62_public_chat_json_compacts_large_failure_report():
    payload = ChatRuntimeResult(
        status="failed",
        thread_id="thread-large-failure",
        turn_id="turn-large-failure",
        route="new_task",
        task_id="task-large-failure",
        run_id="run-1",
        answer="short user-visible failure answer",
        final_answer=None,
        failure_report={
            "reason": "model_planner_processor_failed",
            "attempted_actions": ["retrieval.run"] * 20,
            "attempted_sources": [f"https://example.test/source/{index}" for index in range(500)],
            "missing_evidence": ["retrieval_evidence", "citation_refs", "sufficient_retrieval_evidence"],
            "next_possible_action": "mission_exhausted_or_blocked",
            "host_situation": {
                "failure": {"diagnosis": "processor_or_planning_failure"},
                "retrieval": {"documents": ["x" * 10000], "fetch_attempts": 500},
            },
        },
        pending_question=None,
        command_result=None,
        summary=None,
        trace_refs=[f"ledger-{index}" for index in range(100)],
    )

    public = public_chat_result_payload(payload)
    encoded = json.dumps(public, ensure_ascii=False, sort_keys=True)

    assert public["answer"] == "short user-visible failure answer"
    assert public["failure_report"]["summary"]
    assert public["failure_report"]["full_report_omitted"] is True
    assert len(public["failure_report"]["attempted_actions"]) == 8
    assert len(public["trace_refs"]) == 16
    assert "source/499" not in encoded
    assert len(encoded) < 5000


def test_phase62_failed_agent_result_still_returns_user_visible_answer():
    class FailedAgent:
        def __init__(self) -> None:
            self.journal = JournalStore.in_memory()

        def run(self, goal: str, **kwargs) -> AgentRuntimeResult:
            return AgentRuntimeResult(
                status="failed",
                task_id="task-failed",
                run_id="run-1",
                mode="retrieval_answer",
                recipe_id="recipe-retrieval-answer",
                final_answer=None,
                failure_report={
                    "reason": "planned_retrieval_subgoals_incomplete",
                    "attempted_actions": ["retrieval.run"],
                    "attempted_sources": [],
                    "missing_evidence": ["sufficient_retrieval_evidence"],
                    "last_observations": [
                        {
                            "content": {
                                "reason": "retrieval source not configured",
                            }
                        }
                    ],
                    "user_help_needed": False,
                    "next_possible_action": "enable_live_retrieval",
                    "task_id": "task-failed",
                    "run_id": "run-1",
                    "trace_refs": ["ledger-1"],
                },
                trace_refs=["ledger-1"],
            )

    journal = JournalStore.in_memory()
    chat = ChatRuntime(journal=journal, agent_runtime=FailedAgent())  # type: ignore[arg-type]

    result = chat.receive("查一下 NVIDIA 基本面", thread_id="thread-failed")

    assert result.status == "failed"
    assert result.answer is not None
    assert "我这次没有拿到足够证据" in result.answer
    assert "retrieval.run" in result.answer
    assert result.failure_report is not None


def test_phase62_human_console_streams_activity_before_final_result(capsys):
    class StreamingRuntime:
        def __init__(self) -> None:
            self.journal = JournalStore.in_memory()

        def receive(self, text: str, *, thread_id: str = "default") -> ChatRuntimeResult:
            self.journal.append(
                task_id="task-stream",
                run_id="run-1",
                step_id=None,
                kind="processor_request",
                data={"task_type": "planner.propose", "provider": "fake", "model": "fake"},
            )
            self.journal.append(
                task_id="task-stream",
                run_id="run-1",
                step_id="step-1",
                kind="action",
                data={"name": "respond", "side_effect_class": "none"},
            )
            return ChatRuntimeResult(
                status="completed",
                thread_id=thread_id,
                turn_id="turn-stream",
                route="new_task",
                task_id="task-stream",
                run_id="run-1",
                answer="done",
                final_answer=None,
                failure_report=None,
                pending_question=None,
                command_result=None,
                summary=None,
                trace_refs=["ledger-1"],
            )

    handle_chat_line(
        StreamingRuntime(),  # type: ignore[arg-type]
        "hello",
        thread_id="thread-stream",
        output_mode="human",
        color=False,
    )

    output = capsys.readouterr().out
    assert "processing..." in output
    assert "steps" in output
    assert "model request planner.propose" in output
    assert "action respond" in output
    assert output.index("model request planner.propose") < output.index("completed task=task-stream")
    assert output.endswith("\n\n")


def test_phase62_cli_once_human_output_streams_activity_before_final_result(tmp_path: Path, capsys):
    journal_path = tmp_path / "journal.jsonl"
    index_path = tmp_path / "journal.sqlite"

    assert (
        cli.main(
            [
                "--journal",
                str(journal_path),
                "--index",
                str(index_path),
                "chat",
                "--thread",
                "once-human",
                "--once",
                "explain Holo briefly",
                "--output",
                "human",
                "--offline",
            ]
        )
        == 0
    )

    output = capsys.readouterr().out
    assert "processing..." in output
    assert "steps" in output
    assert "[route] route" in output
    assert "[context] context compiled" in output
    assert "completed task=" in output
    assert output.index("steps") < output.index("completed task=")


def _run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "kernel_v3.cli", *args],
        cwd=Path(__file__).resolve().parents[1],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )


class CapturingAgentRuntime:
    processor_fabric = None
    memory_store = None

    def __init__(self) -> None:
        self.resume_calls: list[dict] = []

    def resume(
        self,
        task_id: str,
        user_input: str,
        *,
        thread_id: str,
        mode: str,
        planner_mode: str,
        evaluator_mode: str,
        synthesizer_mode: str,
        semantic_mode: str,
        execution_metadata: dict | None = None,
        **_kwargs,
    ) -> AgentRuntimeResult:
        self.resume_calls.append(
            {
                "task_id": task_id,
                "user_input": user_input,
                "thread_id": thread_id,
                "mode": mode,
                "planner_mode": planner_mode,
                "evaluator_mode": evaluator_mode,
                "synthesizer_mode": synthesizer_mode,
                "semantic_mode": semantic_mode,
                "execution_metadata": dict(execution_metadata or {}),
            }
        )
        return AgentRuntimeResult(
            status="completed",
            task_id=task_id,
            run_id="run-captured",
            mode=mode,
            recipe_id="recipe-captured",
            final_answer={
                "answer": "captured",
                "citation_refs": [],
                "used_evidence": [],
                "limitations": [],
                "confidence": 0.5,
                "task_id": task_id,
                "run_id": "run-captured",
                "trace_refs": [],
            },
            failure_report=None,
            trace_refs=[],
        )


class CapturingFakeJsonProvider(FakeJsonProvider):
    def __init__(self, responses):
        super().__init__(responses)
        self.last_prompt = ""

    def run(self, request):
        self.last_prompt = request.prompt
        return super().run(request)


def _chat_with_semantic(
    journal: JournalStore,
    responses: list[dict],
    *,
    workspace_files: dict[str, str] | None = None,
) -> ChatRuntime:
    fabric = fake_fabric({"semantic.intake": responses}, journal=journal)
    agent = AgentRuntime(journal=journal, processor_fabric=fabric, workspace_files=workspace_files)
    return ChatRuntime(journal=journal, agent_runtime=agent, semantic_mode="model")


def _workspace_read_intake() -> dict:
    return {
        "primary_intent": "workspace_read",
        "suggested_mode": "workspace_answer",
        "compound": False,
        "requires_clarification": False,
        "intents": [
            {
                "kind": "workspace_read",
                "text": "read a workspace target",
                "sequence_index": 1,
                "required_capabilities": ["workspace.search", "file.read"],
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


def _direct_intake() -> dict:
    return {
        "primary_intent": "direct_answer",
        "suggested_mode": "direct_answer",
        "compound": False,
        "requires_clarification": False,
        "intents": [
            {
                "kind": "direct_answer",
                "text": "direct current-turn answer",
                "sequence_index": 1,
                "required_capabilities": [],
                "risk": "none",
                "status": "ready",
                "metadata": {},
            }
        ],
        "blocked_capabilities": [],
        "warnings": [],
        "response_hint": None,
        "clarification_question": None,
    }


def _clarify_intake() -> dict:
    return {
        "primary_intent": "clarification",
        "suggested_mode": "clarify_first",
        "compound": False,
        "requires_clarification": True,
        "intents": [
            {
                "kind": "clarification",
                "text": "vague help request",
                "sequence_index": 1,
                "required_capabilities": [],
                "risk": "none",
                "status": "needs_user_input",
                "metadata": {},
            }
        ],
        "blocked_capabilities": [],
        "warnings": [],
        "response_hint": None,
        "clarification_question": "请问您对什么内容不太明白？",
    }


def _corpus_with_document(artifacts: ArtifactStore, *, query_text: str) -> ResearchCorpusStore:
    corpus = ResearchCorpusStore.in_memory(clock_ms=lambda: 101)
    uri = "local://kernel-v3/phase62-corpus"
    title = "Phase62 local corpus source"
    body = f"{query_text} corpus evidence from a local indexed source."
    source = SearchSource(
        source_id="src-phase62-corpus",
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
                document_id="doc-phase62-corpus",
                goal_id="goal-phase62-corpus",
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
            goal=SearchGoal(goal_id="goal-phase62-corpus", query=query_text),
            task_id="task-phase62-corpus",
            run_id="run-phase62-corpus",
            fetched_at_ms=101,
        )
    )
    return corpus
