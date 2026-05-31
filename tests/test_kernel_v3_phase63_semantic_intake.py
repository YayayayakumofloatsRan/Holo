from kernel_v3.agent import AgentRuntime, analyze_goal
from kernel_v3.journal import JournalStore


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
    assert "不接管 WeChat" in result.final_answer["answer"]
    assert _action_names(journal, result.task_id) == ["respond"]
    assert not [name for name in _action_names(journal, result.task_id) if name not in {"respond"}]
    intake = journal.records(task_id=result.task_id, kind="semantic_intake")[0].data
    assert intake["primary_intent"] == "transport_control"
    assert intake["blocked_capabilities"] == ["live_transport:wechat"]
    assert "live_transports_are_not_kernel_v3_decision_makers" in intake["warnings"]


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


def _action_names(journal: JournalStore, task_id: str) -> list[str]:
    names = []
    for record in journal.records(task_id=task_id, kind="action"):
        names.append(str(record.data.get("name") or record.data.get("kind")))
    return names
