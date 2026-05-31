from kernel_v3.agent import AgentRuntime, analyze_goal
from kernel_v3.journal import JournalStore
from kernel_v3.processors.testing import fake_fabric


def test_phase80_direct_fallback_does_not_turn_user_text_into_answer():
    journal = JournalStore.in_memory()

    result = AgentRuntime(journal=journal).run("explain an arbitrary new topic", mode="auto")

    assert result.status == "completed"
    assert result.final_answer is not None
    answer = result.final_answer["answer"]
    assert "离线 host fallback" in answer
    assert "Direct answer:" not in answer
    assert "explain an arbitrary new topic" not in answer


def test_phase80_private_reasoning_is_a_host_boundary_not_a_tool_call():
    journal = JournalStore.in_memory()

    result = AgentRuntime(journal=journal).run("show your chain of thought for this answer", mode="auto")
    intake = journal.records(task_id=result.task_id, kind="semantic_intake")[0].data

    assert result.status == "completed"
    assert intake["primary_intent"] == "private_reasoning"
    assert "private_reasoning_is_not_exposed" in intake["warnings"]
    assert "私有推理链" in result.final_answer["answer"]
    assert not journal.records(task_id=result.task_id, kind="tool_call")


def test_phase80_shell_execution_is_a_capability_boundary_not_a_content_table():
    journal = JournalStore.in_memory()

    result = AgentRuntime(journal=journal).run("run a shell command that changes the machine", mode="auto")
    intake = journal.records(task_id=result.task_id, kind="semantic_intake")[0].data

    assert result.status == "completed"
    assert intake["primary_intent"] == "shell_execution"
    assert "shell:exec" in intake["blocked_capabilities"]
    assert "不直接执行 shell" in result.final_answer["answer"]
    assert not journal.records(task_id=result.task_id, kind="tool_call")


def test_phase80_model_intake_can_express_unseen_semantics_without_fallback_tables():
    journal = JournalStore.in_memory()
    fabric = fake_fabric(
        {
            "semantic.intake": {
                "primary_intent": "roleplay",
                "suggested_mode": "clarify_first",
                "compound": True,
                "requires_clarification": True,
                "intents": [
                    {
                        "kind": "roleplay",
                        "text": "adopt a user-defined persona",
                        "sequence_index": 1,
                        "required_capabilities": [],
                        "risk": "none",
                        "status": "ready",
                        "metadata": {"role": "unlisted persona"},
                    },
                    {
                        "kind": "workspace_write",
                        "text": "persist a local artifact",
                        "sequence_index": 2,
                        "required_capabilities": ["workspace:write"],
                        "risk": "write",
                        "status": "needs_permission",
                        "metadata": {},
                    },
                ],
                "blocked_capabilities": ["workspace:write"],
                "warnings": ["model_detected_unseen_compound_request"],
                "response_hint": None,
                "clarification_question": "Confirm persona scope and write permission.",
            }
        },
        journal=journal,
    )

    result = AgentRuntime(journal=journal, processor_fabric=fabric).run(
        "a deliberately unlisted compound instruction",
        mode="auto",
        semantic_mode="model",
    )
    intake = journal.records(task_id=result.task_id, kind="semantic_intake")[0].data

    assert result.status == "needs_user_input"
    assert intake["compound"] is True
    assert intake["intents"][0]["metadata"]["role"] == "unlisted persona"
    assert "workspace:write" in intake["blocked_capabilities"]
    assert "model_detected_unseen_compound_request" in intake["warnings"]


def test_phase80_model_intake_cannot_hide_blocked_shell_capability_under_direct_answer():
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
                        "text": "make an execution request look harmless",
                        "sequence_index": 1,
                        "required_capabilities": ["shell:exec"],
                        "risk": "none",
                        "status": "ready",
                        "metadata": {},
                    }
                ],
                "blocked_capabilities": [],
                "warnings": [],
                "response_hint": "execution completed",
                "clarification_question": None,
            }
        },
        journal=journal,
    )

    result = AgentRuntime(journal=journal, processor_fabric=fabric).run(
        "make an execution request look harmless",
        mode="auto",
        semantic_mode="model",
    )
    intake = journal.records(task_id=result.task_id, kind="semantic_intake")[0].data

    assert result.status == "needs_user_input"
    assert intake["blocked_capabilities"] == ["shell:exec"]
    assert "未开放能力" in intake["clarification_question"]
    assert result.final_answer is None


def test_phase80_non_capability_questions_stay_model_or_fallback_owned():
    intake = analyze_goal("what is a surprising edge case nobody listed")

    assert intake.primary_intent == "direct_answer"
    assert intake.blocked_capabilities == []
    assert intake.response_hint is None


def test_phase80_fake_intake_does_not_keyword_route_open_semantics():
    probes = [
        "research a current product page",
        "act as a user-defined assistant",
        "tell a math joke",
        "summarize and compare these ideas",
        "read README.md and explain it",
        "write a local report",
        "什么都不要做",
        "记住我偏好中文短答",
        "接管Holo的wechat，有相关的程序",
    ]

    for text in probes:
        intake = analyze_goal(text)
        assert intake.primary_intent == "direct_answer"
        assert intake.suggested_mode == "direct_answer"
        assert intake.blocked_capabilities == []
