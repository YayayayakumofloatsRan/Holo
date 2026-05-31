from kernel_v3.agent import AgentRuntime, analyze_goal
from kernel_v3.journal import JournalStore
from kernel_v3.processors.testing import fake_fabric


def test_phase63_roleplay_request_is_scoped_direct_response_not_echo():
    journal = JournalStore.in_memory()
    result = AgentRuntime(journal=journal).run("你去扮演Jarvis", mode="auto")

    assert result.status == "completed"
    assert result.mode == "direct_answer"
    assert result.final_answer is not None
    assert "Jarvis" in result.final_answer["answer"]
    assert "不会改变系统权限" in result.final_answer["answer"]
    assert "Direct answer:" not in result.final_answer["answer"]
    intake = journal.records(task_id=result.task_id, kind="semantic_intake")[0].data
    assert intake["primary_intent"] == "roleplay"
    assert intake["warnings"] == ["roleplay_scope_is_current_thread_only"]


def test_phase63_compound_task_is_not_flattened_into_single_retrieval():
    journal = JournalStore.in_memory()
    goal = "先去搜索deepseek的api文档，然后本地写一个报告，再去搜一下它的国内竞品，kimi之类，再扩展一下思路，最后给我讲个笑话，再扮演jarvis"

    result = AgentRuntime(journal=journal).run(goal, mode="auto")

    assert result.status == "needs_user_input"
    assert result.mode == "clarify_first"
    assert result.final_answer is None
    assert not journal.records(task_id=result.task_id, kind="retrieval_report")
    assert _action_names(journal, result.task_id) == ["ask_user"]
    observation = journal.records(task_id=result.task_id, kind="observation")[0].data
    assert "检测到复合任务" in observation["content"]["question"]
    assert "workspace:write" in observation["content"]["question"]
    intake = journal.records(task_id=result.task_id, kind="semantic_intake")[0].data
    assert intake["compound"] is True
    assert "workspace:write" in intake["blocked_capabilities"]
    assert {item["kind"] for item in intake["intents"]} >= {"retrieval_research", "workspace_write", "roleplay"}


def test_phase63_transport_control_request_is_refused_without_tool_execution():
    journal = JournalStore.in_memory()
    result = AgentRuntime(journal=journal).run("接管Holo的wechat，有相关的程序", mode="auto")

    assert result.status == "completed"
    assert result.mode == "direct_answer"
    assert result.final_answer is not None
    assert "不接管" in result.final_answer["answer"]
    assert "live transport" in result.final_answer["answer"]
    assert _action_names(journal, result.task_id) == ["respond"]
    assert not [name for name in _action_names(journal, result.task_id) if name not in {"respond"}]
    intake = journal.records(task_id=result.task_id, kind="semantic_intake")[0].data
    assert intake["primary_intent"] == "transport_control"
    assert intake["blocked_capabilities"] == ["live_transport:wechat"]
    assert "live_transports_are_not_kernel_v3_decision_makers" in intake["warnings"]


def test_phase63_roleplay_extracts_role_without_known_role_table():
    intake = analyze_goal("请扮演Ada Lovelace来解释这个系统")

    assert intake.primary_intent == "roleplay"
    assert intake.intents[0]["metadata"]["role"] == "Ada Lovelace"
    assert intake.suggested_mode == "direct_answer"


def test_phase63_noop_request_does_not_execute_tools():
    journal = JournalStore.in_memory()
    result = AgentRuntime(journal=journal).run("什么都不要做", mode="auto")

    assert result.status == "completed"
    assert result.final_answer is not None
    assert "不会执行任何工具" in result.final_answer["answer"]
    assert _action_names(journal, result.task_id) == ["respond"]
    intake = journal.records(task_id=result.task_id, kind="semantic_intake")[0].data
    assert intake["primary_intent"] == "noop"
    assert intake["blocked_capabilities"] == []


def test_phase63_semantic_intake_preserves_simple_retrieval_route():
    intake = analyze_goal("搜索 DeepSeek API 文档")

    assert intake.primary_intent == "retrieval_research"
    assert intake.suggested_mode == "retrieval_answer"
    assert intake.requires_clarification is False
    assert intake.compound is False


def test_phase63_model_semantic_intake_drives_open_ended_decomposition():
    journal = JournalStore.in_memory()
    fabric = fake_fabric(
        {
            "semantic.intake": {
                "primary_intent": "retrieval_research",
                "suggested_mode": "clarify_first",
                "compound": True,
                "requires_clarification": True,
                "intents": [
                    {
                        "kind": "retrieval_research",
                        "text": "research a current API surface",
                        "sequence_index": 1,
                        "required_capabilities": ["retrieval.run"],
                        "risk": "read",
                        "status": "ready",
                        "metadata": {"topic": "api docs"},
                    },
                    {
                        "kind": "workspace_write",
                        "text": "write a local report",
                        "sequence_index": 2,
                        "required_capabilities": ["workspace:write"],
                        "risk": "write",
                        "status": "needs_permission",
                        "metadata": {},
                    },
                    {
                        "kind": "roleplay",
                        "text": "answer in a named assistant style",
                        "sequence_index": 3,
                        "required_capabilities": [],
                        "risk": "none",
                        "status": "ready",
                        "metadata": {"role": "custom assistant"},
                    },
                ],
                "blocked_capabilities": ["workspace:write"],
                "warnings": ["model_detected_compound_task"],
                "response_hint": None,
                "clarification_question": "Confirm the ordered plan and write permission before execution.",
            }
        },
        journal=journal,
    )

    result = AgentRuntime(journal=journal, processor_fabric=fabric).run(
        "A broad multi-step request the fallback has never seen",
        mode="auto",
        semantic_mode="model",
    )

    assert result.status == "needs_user_input"
    assert result.mode == "clarify_first"
    assert result.task_id == "task-1"
    assert result.run_id == "run-1"
    assert not journal.records(task_id=result.task_id, kind="retrieval_report")
    intake = journal.records(task_id=result.task_id, kind="semantic_intake")[0].data
    assert intake["intents"][0]["text"] == "research a current API surface"
    assert "workspace:write" in intake["blocked_capabilities"]
    assert "model_detected_compound_task" in intake["warnings"]
    processor_results = journal.records(task_id=result.task_id, kind="processor_result")
    assert [record.data["task_type"] for record in processor_results] == ["semantic.intake"]
    assert processor_results[0].run_id == result.run_id


def test_phase63_model_semantic_intake_response_hint_cannot_become_final_answer():
    journal = JournalStore.in_memory()
    fabric = fake_fabric(
        {
            "semantic.intake": {
                "primary_intent": "direct_answer",
                "suggested_mode": "direct_answer",
                "compound": False,
                "requires_clarification": False,
                "intents": [
                    {
                        "kind": "direct_answer",
                        "text": "answer a local direct question",
                        "sequence_index": 1,
                        "required_capabilities": [],
                        "risk": "none",
                        "status": "ready",
                        "metadata": {},
                    }
                ],
                "blocked_capabilities": [],
                "warnings": [],
                "response_hint": "UNSUPPORTED FACTUAL ANSWER FROM SEMANTIC INTAKE",
                "clarification_question": None,
            }
        },
        journal=journal,
    )

    result = AgentRuntime(journal=journal, processor_fabric=fabric).run(
        "answer a local direct question",
        mode="auto",
        semantic_mode="model",
    )

    assert result.status == "completed"
    assert result.final_answer is not None
    assert "离线 host fallback" in result.final_answer["answer"]
    assert "Direct answer:" not in result.final_answer["answer"]
    assert result.final_answer["answer"] != "UNSUPPORTED FACTUAL ANSWER FROM SEMANTIC INTAKE"
    intake = journal.records(task_id=result.task_id, kind="semantic_intake")[0].data
    assert intake["response_hint"] is None


def test_phase63_model_semantic_intake_cannot_hide_blocked_capability_under_safe_kind():
    journal = JournalStore.in_memory()
    fabric = fake_fabric(
        {
            "semantic.intake": {
                "primary_intent": "direct_answer",
                "suggested_mode": "direct_answer",
                "compound": False,
                "requires_clarification": False,
                "intents": [
                    {
                        "kind": "direct_answer",
                        "text": "remember this preference",
                        "sequence_index": 1,
                        "required_capabilities": ["durable_memory:write"],
                        "risk": "none",
                        "status": "ready",
                        "metadata": {},
                    }
                ],
                "blocked_capabilities": [],
                "warnings": [],
                "response_hint": "I will remember it.",
                "clarification_question": None,
            }
        },
        journal=journal,
    )

    result = AgentRuntime(journal=journal, processor_fabric=fabric).run(
        "remember my preference",
        mode="auto",
        semantic_mode="model",
    )

    assert result.status == "needs_user_input"
    intake = journal.records(task_id=result.task_id, kind="semantic_intake")[0].data
    assert intake["blocked_capabilities"] == ["durable_memory:write"]
    assert "未开放能力" in intake["clarification_question"]


def test_phase63_model_semantic_intake_resume_uses_next_real_run_id():
    journal = JournalStore.in_memory()
    runtime = AgentRuntime(journal=journal, workspace_files={"README.md": "resume evidence"})
    pending = runtime.run("read the file", mode="workspace")
    fabric = fake_fabric(
        {
            "semantic.intake": {
                "primary_intent": "workspace_read",
                "suggested_mode": "workspace_answer",
                "compound": False,
                "requires_clarification": False,
                "intents": [
                    {
                        "kind": "workspace_read",
                        "text": "README.md",
                        "sequence_index": 1,
                        "required_capabilities": ["file.read"],
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

    resumed = AgentRuntime(journal=journal, processor_fabric=fabric, workspace_files={"README.md": "resume evidence"}).resume(
        pending.task_id,
        "README.md",
        mode="auto",
        semantic_mode="model",
    )

    assert resumed.status == "completed"
    assert resumed.task_id == pending.task_id
    assert resumed.run_id == "run-2"
    processor_results = journal.records(task_id=pending.task_id, kind="processor_result")
    assert processor_results[0].run_id == "run-2"


def _action_names(journal: JournalStore, task_id: str) -> list[str]:
    names = []
    for record in journal.records(task_id=task_id, kind="action"):
        names.append(str(record.data.get("name") or record.data.get("kind")))
    return names
