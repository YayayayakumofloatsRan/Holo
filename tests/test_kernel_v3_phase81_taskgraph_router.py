from kernel_v3.agent import AgentRuntime, build_task_execution_plan, task_graph_from_semantic, validate_task_graph
from kernel_v3.agent.contracts import SemanticIntake, TaskGraphProposal
from kernel_v3.chat import ChatRuntime
from kernel_v3.context import ArtifactStore
from kernel_v3.journal import JournalStore
from kernel_v3.processors.testing import fake_fabric
from kernel_v3.retrieval import FakeFetchProvider, FakeSearchProvider, RetrievalOperator


def test_phase81_model_semantics_are_journaled_as_validated_task_graph():
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
                        "metadata": {},
                    },
                    {
                        "kind": "workspace_write",
                        "text": "write a local report after research",
                        "sequence_index": 2,
                        "required_capabilities": ["workspace:write"],
                        "risk": "write",
                        "status": "needs_permission",
                        "metadata": {},
                    },
                ],
                "blocked_capabilities": ["workspace:write"],
                "warnings": ["model_detected_compound_task"],
                "response_hint": None,
                "clarification_question": "Confirm the ordered plan and write permission.",
            }
        },
        journal=journal,
    )

    result = AgentRuntime(journal=journal, processor_fabric=fabric).run(
        "unlisted compound research and write request",
        mode="auto",
        semantic_mode="model",
    )
    graph_record = journal.records(task_id=result.task_id, kind="semantic_task_graph")[0].data
    plan_record = journal.records(task_id=result.task_id, kind="semantic_task_plan")[0].data
    proposal = graph_record["proposal"]
    validation = graph_record["validation"]

    assert result.status == "needs_user_input"
    assert proposal["nodes"][0]["suggested_mode"] == "retrieval_answer"
    assert proposal["nodes"][1]["depends_on"] == [proposal["nodes"][0]["node_id"]]
    assert validation["status"] == "needs_user_confirmation"
    assert validation["selected_mode"] == "clarify_first"
    assert "workspace:write" in validation["blocked_capabilities"]
    assert "user_confirmation_required" in validation["reasons"]
    assert plan_record["status"] == "needs_user_confirmation"
    assert plan_record["approval_required"] is True
    assert plan_record["steps"][0]["action_kind"] == "tool"
    assert plan_record["steps"][0]["tool_name"] == "retrieval.run"
    assert plan_record["steps"][1]["status"] == "blocked"
    assert not journal.records(task_id=result.task_id, kind="retrieval_report")


def test_phase81_simple_retrieval_graph_selects_retrieval_recipe():
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
                        "text": "research current docs",
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

    result = AgentRuntime(journal=journal, processor_fabric=fabric).run(
        "an unseen current documentation request",
        mode="auto",
        semantic_mode="model",
    )
    validation = journal.records(task_id=result.task_id, kind="semantic_task_graph")[0].data["validation"]
    plan = journal.records(task_id=result.task_id, kind="semantic_task_plan")[0].data

    assert result.mode == "retrieval_answer"
    assert result.status == "completed"
    assert validation["status"] == "ready"
    assert validation["selected_mode"] == "retrieval_answer"
    assert plan["status"] == "ready"
    assert plan["approval_required"] is False
    assert plan["steps"][0]["tool_name"] == "retrieval.run"
    assert journal.records(task_id=result.task_id, kind="retrieval_report")


def test_phase81_open_semantic_label_routes_by_capability_not_intent_table():
    journal = JournalStore.in_memory()
    fabric = fake_fabric(
        {
            "semantic.intake": {
                "primary_intent": "市场态势梳理",
                "suggested_mode": "direct_answer",
                "compound": False,
                "requires_clarification": False,
                "intents": [
                    {
                        "kind": "市场态势梳理",
                        "text": "compare current market signals from evidence",
                        "sequence_index": 1,
                        "required_capabilities": ["retrieval.run"],
                        "risk": "read",
                        "status": "ready",
                        "metadata": {"success_criteria": ["grounded answer"]},
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

    result = AgentRuntime(journal=journal, processor_fabric=fabric).run(
        "unseen market landscape request",
        mode="auto",
        semantic_mode="model",
    )
    graph = journal.records(task_id=result.task_id, kind="semantic_task_graph")[0].data
    plan = journal.records(task_id=result.task_id, kind="semantic_task_plan")[0].data

    assert result.mode == "retrieval_answer"
    assert result.status == "completed"
    assert graph["proposal"]["nodes"][0]["kind"] == "市场态势梳理"
    assert graph["proposal"]["nodes"][0]["metadata"]["semantic_label"] == "市场态势梳理"
    assert graph["validation"]["selected_mode"] == "retrieval_answer"
    assert plan["steps"][0]["action_kind"] == "tool"
    assert plan["steps"][0]["tool_name"] == "retrieval.run"
    assert plan["steps"][0]["evidence_required"] is True
    assert plan["steps"][0]["citations_required"] is True
    assert journal.records(task_id=result.task_id, kind="retrieval_report")


def test_phase81_workspace_write_without_payload_asks_user_without_blocking_capability():
    journal = JournalStore.in_memory()
    fabric = fake_fabric(
        {
            "semantic.intake": {
                "primary_intent": "任意本地产物生成",
                "suggested_mode": "direct_answer",
                "compound": False,
                "requires_clarification": False,
                "intents": [
                    {
                        "kind": "任意本地产物生成",
                        "text": "create a local report",
                        "sequence_index": 1,
                        "required_capabilities": ["workspace:write"],
                        "risk": "write",
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

    result = AgentRuntime(journal=journal, processor_fabric=fabric).run(
        "unseen local artifact request",
        mode="auto",
        semantic_mode="model",
    )
    validation = journal.records(task_id=result.task_id, kind="semantic_task_graph")[0].data["validation"]
    plan = journal.records(task_id=result.task_id, kind="semantic_task_plan")[0].data

    assert result.status == "needs_user_input"
    assert validation["blocked_capabilities"] == []
    assert validation["selected_mode"] == "workspace_write"
    assert plan["steps"][0]["kind"] == "任意本地产物生成"
    assert plan["steps"][0]["status"] == "ready"
    assert plan["steps"][0]["tool_name"] == "workspace.write"
    assert not any(record.data.get("name") == "workspace.write" for record in journal.records(task_id=result.task_id, kind="action"))


def test_phase81_workspace_capability_args_replace_filename_phrase_parsing():
    journal = JournalStore.in_memory()
    fabric = fake_fabric(
        {
            "semantic.intake": {
                "primary_intent": "project_overview_read",
                "suggested_mode": "direct_answer",
                "compound": False,
                "requires_clarification": False,
                "intents": [
                    {
                        "kind": "project_overview_read",
                        "text": "inspect the project overview artifact",
                        "sequence_index": 1,
                        "required_capabilities": ["workspace.search", "file.read"],
                        "risk": "read",
                        "status": "ready",
                        "metadata": {
                            "capability_args": {
                                "workspace.search": {"query": "overview"},
                                "file.read": {"path": "docs/overview.holo"},
                            }
                        },
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
    runtime = AgentRuntime(
        journal=journal,
        processor_fabric=fabric,
        workspace_files={"docs/overview.holo": "Workspace capability args grounded this answer."},
    )

    result = runtime.run(
        "inspect the project overview artifact",
        mode="auto",
        semantic_mode="model",
    )
    graph = journal.records(task_id=result.task_id, kind="semantic_task_graph")[0].data
    plan = journal.records(task_id=result.task_id, kind="semantic_task_plan")[0].data
    actions = [record.data for record in journal.records(task_id=result.task_id, kind="action")]

    assert result.status == "completed"
    assert result.mode == "workspace_answer"
    assert graph["proposal"]["nodes"][0]["kind"] == "project_overview_read"
    assert plan["steps"][0]["metadata"]["capability_args"]["file.read"]["path"] == "docs/overview.holo"
    assert [action["name"] for action in actions] == ["workspace.search", "file.read"]
    assert actions[0]["payload"] == {"query": "overview"}
    assert actions[1]["payload"] == {"path": "docs/overview.holo"}
    assert result.final_answer is not None
    assert "Workspace capability args" in result.final_answer["answer"]


def test_phase81_safe_compound_workspace_plan_executes_without_confirmation():
    journal = JournalStore.in_memory()
    fabric = fake_fabric(
        {
            "semantic.intake": {
                "primary_intent": "workspace_read",
                "suggested_mode": "workspace_answer",
                "compound": True,
                "requires_clarification": False,
                "intents": [
                    {
                        "kind": "workspace_read",
                        "text": "inspect README.md",
                        "sequence_index": 1,
                        "required_capabilities": ["workspace.search", "file.read"],
                        "risk": "read",
                        "status": "ready",
                        "metadata": {
                            "capability_args": {
                                "workspace.search": {"query": "kernel v3 mainline legacy stage"},
                                "file.read": {"path": "README.md"},
                            }
                        },
                    },
                    {
                        "kind": "answer_from_workspace",
                        "text": "answer from the inspected README",
                        "sequence_index": 2,
                        "required_capabilities": [],
                        "risk": "none",
                        "status": "ready",
                        "metadata": {},
                    },
                ],
                "blocked_capabilities": [],
                "warnings": ["model_detected_safe_compound_task"],
                "response_hint": None,
                "clarification_question": None,
            }
        },
        journal=journal,
    )
    runtime = AgentRuntime(
        journal=journal,
        processor_fabric=fabric,
        workspace_files={"README.md": "Kernel v3 is the active mainline. Legacy stage docs are reference only."},
    )

    result = runtime.run(
        "只读检查 README.md，告诉我 kernel v3 当前主线是什么，以及旧 stage 线是否还应该作为当前施工对象。",
        mode="auto",
        semantic_mode="model",
    )
    validation = journal.records(task_id=result.task_id, kind="semantic_task_graph")[0].data["validation"]
    plan = journal.records(task_id=result.task_id, kind="semantic_task_plan")[0].data
    actions = [record.data for record in journal.records(task_id=result.task_id, kind="action")]

    assert result.status == "completed"
    assert result.mode == "workspace_answer"
    assert validation["status"] == "ready"
    assert validation["selected_mode"] == "workspace_answer"
    assert plan["approval_required"] is False
    assert [action["name"] for action in actions] == ["workspace.search", "file.read"]
    assert actions[1]["payload"] == {"path": "README.md"}
    assert not any(action["kind"] == "ask_user" for action in actions)
    assert result.final_answer is not None
    assert "Kernel v3 is the active mainline" in result.final_answer["answer"]


def test_phase81_blocked_capability_in_model_graph_cannot_select_tool_recipe():
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
                        "text": "smuggled execution request",
                        "sequence_index": 1,
                        "required_capabilities": ["shell:exec"],
                        "risk": "shell",
                        "status": "blocked",
                        "metadata": {},
                    }
                ],
                "blocked_capabilities": [],
                "warnings": [],
                "response_hint": "I ran it.",
                "clarification_question": None,
            }
        },
        journal=journal,
    )

    result = AgentRuntime(journal=journal, processor_fabric=fabric).run(
        "model tries to hide a machine execution capability",
        mode="auto",
        semantic_mode="model",
    )
    validation = journal.records(task_id=result.task_id, kind="semantic_task_graph")[0].data["validation"]
    plan = journal.records(task_id=result.task_id, kind="semantic_task_plan")[0].data

    assert result.status == "needs_user_input"
    assert validation["selected_mode"] == "clarify_first"
    assert validation["blocked_capabilities"] == ["shell:exec"]
    assert plan["approval_required"] is True
    assert plan["steps"][0]["status"] == "blocked"
    assert not journal.records(task_id=result.task_id, kind="tool_call")


def test_phase81_task_graph_validator_rejects_invalid_dependencies():
    proposal = TaskGraphProposal(
        graph_id="graph-invalid",
        goal="invalid graph",
        nodes=[
            {
                "node_id": "node-1-direct_answer",
                "kind": "direct_answer",
                "goal": "answer",
                "sequence_index": 1,
                "depends_on": ["missing-node"],
                "required_capabilities": [],
                "suggested_mode": "direct_answer",
                "evidence_required": False,
                "citations_required": False,
                "status": "ready",
                "metadata": {},
            }
        ],
        blocked_capabilities=[],
        warnings=[],
        needs_user_confirmation=False,
        clarification_question=None,
        max_steps=2,
        max_tool_calls=0,
        metadata={},
    )

    validation = validate_task_graph(proposal)
    plan = build_task_execution_plan(proposal, validation)

    assert validation.status == "invalid"
    assert validation.selected_mode == "clarify_first"
    assert validation.rejected_node_ids == ["node-1-direct_answer"]
    assert "invalid_task_graph_dependencies" in validation.reasons
    assert plan.status == "invalid"
    assert plan.steps[0]["status"] == "invalid"
    assert plan.approval_required is True


def test_phase81_boundary_only_fallback_still_gets_direct_graph():
    intake = SemanticIntake(
        intake_id="semantic-intake-1",
        goal="记住我偏好中文短答",
        primary_intent="direct_answer",
        suggested_mode="direct_answer",
        compound=False,
        requires_clarification=False,
        intents=[],
        blocked_capabilities=[],
        warnings=[],
        response_hint=None,
        clarification_question=None,
    )

    proposal = task_graph_from_semantic(intake)
    validation = validate_task_graph(proposal)
    plan = build_task_execution_plan(proposal, validation)

    assert proposal.nodes[0]["kind"] == "direct_answer"
    assert validation.status == "ready"
    assert validation.selected_mode == "direct_answer"
    assert plan.status == "ready"
    assert plan.approval_required is False


def test_phase81_chat_plan_show_lists_latest_model_task_plan():
    journal = JournalStore.in_memory()
    chat = _chat_with_semantic_plan(journal, _compound_research_write_intake())

    initial = chat.receive("compound task requiring confirmation", thread_id="thread-plan-show")
    shown = chat.receive("/plan", thread_id="thread-plan-show")

    assert initial.status == "needs_user_input"
    assert shown.route == "command"
    assert shown.status == "completed"
    assert shown.command_result is not None
    assert shown.command_result["result"]["plan_id"] == "plan-task-graph-1"
    assert shown.command_result["result"]["progress"]["completed_step_count"] == 0
    assert shown.command_result["result"]["progress"]["steps"][0]["progress_status"] == "pending"
    assert "plan=plan-task-graph-1" in (shown.answer or "")
    assert "completed_steps=0/2" in (shown.answer or "")
    assert "retrieval.run" in (shown.answer or "")
    assert "workspace:write" in (shown.answer or "")


def test_phase81_chat_plan_approve_executes_first_safe_step_only():
    journal = JournalStore.in_memory()
    chat = _chat_with_semantic_plan(journal, _compound_research_write_intake())

    initial = chat.receive("compound task requiring confirmation", thread_id="thread-plan-approve")
    approved = chat.receive("/plan approve", thread_id="thread-plan-approve")

    assert initial.status == "needs_user_input"
    assert approved.route == "command"
    assert approved.status == "completed"
    assert approved.command_result is not None
    assert approved.command_result["started_new_task"] is True
    assert approved.command_result["executed_step_id"] == "plan-step-1"
    assert approved.command_result["spawned_task_id"] != initial.task_id
    decisions = journal.records(task_id=initial.task_id, kind="semantic_task_plan_decision")
    assert decisions[-1].data["decision"] == "approved"
    assert decisions[-1].data["executed_step"]["tool_name"] == "retrieval.run"
    assert decisions[-1].data["spawned_task_id"] == approved.command_result["spawned_task_id"]
    assert journal.records(task_id=approved.command_result["spawned_task_id"], kind="retrieval_report")
    tool_calls = [record.data.get("name") for record in journal.records(kind="tool_call")]
    assert "workspace.write" not in tool_calls

    repeated = chat.receive("/plan approve", thread_id="thread-plan-approve")
    assert repeated.status == "failed"
    assert repeated.command_result is not None
    assert repeated.command_result["result"]["reason"] == "no_safe_executable_step"
    assert len(journal.records(task_id=approved.command_result["spawned_task_id"], kind="retrieval_report")) == 1


def test_phase81_pending_plan_confirmation_can_approve_without_slash_command():
    journal = JournalStore.in_memory()
    chat = _chat_with_semantic_plan(
        journal,
        _compound_research_write_intake(),
        chat_routes=[
            _chat_route("new_task"),
            _chat_route("answer_pending_question", command="approve_plan"),
        ],
    )

    initial = chat.receive("compound task requiring confirmation", thread_id="thread-plan-natural-approve")
    approved = chat.receive("同意", thread_id="thread-plan-natural-approve")

    assert initial.status == "needs_user_input"
    assert approved.route == "answer_pending_question"
    assert approved.status == "completed"
    assert approved.command_result is not None
    assert approved.command_result["decision"] == "approved"
    assert approved.command_result["executed_step_id"] == "plan-step-1"
    assert journal.records(task_id=approved.command_result["spawned_task_id"], kind="retrieval_report")
    assert not journal.records(task_id=initial.task_id, kind="resume")


def test_phase81_fake_mode_does_not_phrase_parse_plan_confirmation():
    journal = JournalStore.in_memory()
    chat = _chat_with_semantic_plan(journal, _compound_research_write_intake())

    initial = chat.receive("compound task requiring confirmation", thread_id="thread-plan-no-phrase-table")
    answered = chat.receive("同意", thread_id="thread-plan-no-phrase-table")

    assert initial.status == "needs_user_input"
    assert answered.route == "answer_pending_question"
    assert answered.command_result is None
    assert not journal.records(task_id=initial.task_id, kind="semantic_task_plan_decision")
    assert not journal.records(kind="retrieval_report")


def test_phase81_pending_plan_confirmation_can_reject_without_resuming_task():
    journal = JournalStore.in_memory()
    chat = _chat_with_semantic_plan(
        journal,
        _compound_research_write_intake(),
        chat_routes=[
            _chat_route("new_task"),
            _chat_route("answer_pending_question", command="reject_plan"),
        ],
    )

    initial = chat.receive("compound task requiring confirmation", thread_id="thread-plan-natural-reject")
    rejected = chat.receive("拒绝", thread_id="thread-plan-natural-reject")

    assert initial.status == "needs_user_input"
    assert rejected.route == "answer_pending_question"
    assert rejected.status == "completed"
    assert rejected.command_result is not None
    assert rejected.command_result["result"]["decision"] == "rejected"
    decisions = journal.records(task_id=initial.task_id, kind="semantic_task_plan_decision")
    assert decisions[-1].data["decision"] == "rejected"
    assert not journal.records(kind="retrieval_report")
    assert not journal.records(task_id=initial.task_id, kind="resume")


def test_phase81_chat_plan_approve_blocks_plan_without_safe_executable_step():
    journal = JournalStore.in_memory()
    chat = _chat_with_semantic_plan(journal, _shell_only_intake())

    initial = chat.receive("unsafe execution task", thread_id="thread-plan-blocked")
    approved = chat.receive("/plan approve", thread_id="thread-plan-blocked")

    assert initial.status == "needs_user_input"
    assert approved.route == "command"
    assert approved.status == "failed"
    assert approved.command_result is not None
    assert approved.command_result["result"]["reason"] == "no_safe_executable_step"
    decisions = journal.records(task_id=initial.task_id, kind="semantic_task_plan_decision")
    assert decisions[-1].data["decision"] == "blocked"
    assert not journal.records(kind="tool_call")


def test_phase81_chat_plan_reject_journals_decision_without_execution():
    journal = JournalStore.in_memory()
    chat = _chat_with_semantic_plan(journal, _compound_research_write_intake())

    initial = chat.receive("compound task requiring confirmation", thread_id="thread-plan-reject")
    rejected = chat.receive("/plan reject plan-task-graph-1 too broad", thread_id="thread-plan-reject")

    assert initial.status == "needs_user_input"
    assert rejected.status == "completed"
    decisions = journal.records(task_id=initial.task_id, kind="semantic_task_plan_decision")
    assert decisions[-1].data["decision"] == "rejected"
    assert decisions[-1].data["reason"] == "too broad"
    assert not journal.records(kind="tool_call")


def test_phase81_chat_plan_approve_can_continue_next_safe_dependent_tool_step():
    journal = JournalStore.in_memory()
    chat = _chat_with_semantic_plan(
        journal,
        _multi_safe_read_after_research_intake(),
        chat_routes=[
            _chat_route("new_task"),
            _chat_route("continue_plan"),
        ],
    )

    initial = chat.receive("safe multi-step plan requiring confirmation", thread_id="thread-plan-continue")
    first = chat.receive("/plan approve", thread_id="thread-plan-continue")
    second = chat.receive("继续", thread_id="thread-plan-continue")
    shown = chat.receive("/plan", thread_id="thread-plan-continue")
    third = chat.receive("/plan approve", thread_id="thread-plan-continue")

    assert initial.status == "needs_user_input"
    assert first.status == "completed"
    assert first.command_result is not None
    assert first.command_result["executed_node_id"] == "node-1-retrieval_research"
    assert second.status == "completed"
    assert second.route == "continue_plan"
    assert second.command_result is not None
    assert second.command_result["executed_node_id"] == "node-2-workspace_read"
    assert third.status == "failed"
    decisions = journal.records(task_id=initial.task_id, kind="semantic_task_plan_decision")
    assert [record.data["decision"] for record in decisions] == ["approved", "approved", "blocked"]
    assert journal.records(task_id=first.command_result["spawned_task_id"], kind="retrieval_report")
    actions = [record.data.get("name") for record in journal.records(task_id=second.command_result["spawned_task_id"], kind="action")]
    assert actions == ["workspace.search", "file.read"]
    progress = shown.command_result["result"]["progress"]
    assert progress["completed_step_count"] == 2
    assert [step["progress_status"] for step in progress["steps"]] == ["completed", "completed"]
    assert "completed_steps=2/2" in (shown.answer or "")


def test_phase81_chat_plan_run_executes_safe_steps_until_finalizer():
    journal = JournalStore.in_memory()
    chat = _chat_with_semantic_plan(journal, _multi_safe_with_finalizer_intake())

    initial = chat.receive("research, read workspace, then synthesize", thread_id="thread-plan-run-finalize")
    result = chat.receive("/plan run", thread_id="thread-plan-run-finalize")
    shown = chat.receive("/plan", thread_id="thread-plan-run-finalize")

    assert initial.status == "needs_user_input"
    assert result.status == "completed"
    assert result.command_result is not None
    assert result.command_result["decision"] == "run_finalized"
    assert [step["executed_node_id"] for step in result.command_result["executed_steps"]] == [
        "node-1-retrieval_research",
        "node-2-workspace_read",
    ]
    assert result.final_answer is not None
    assert result.final_answer["citation_refs"]
    decisions = journal.records(task_id=initial.task_id, kind="semantic_task_plan_decision")
    assert [record.data["decision"] for record in decisions] == ["approved", "approved"]
    assert [record.data["reason"] for record in decisions] == ["run_next_safe_step", "run_next_safe_step"]
    assert len(journal.records(task_id=initial.task_id, kind="semantic_task_plan_final_answer")) == 1
    progress = shown.command_result["result"]["progress"]
    assert progress["finalized"] is True
    assert progress["completed_step_count"] == 2


def test_phase81_chat_plan_run_stops_at_blocked_boundary_after_safe_prefix():
    journal = JournalStore.in_memory()
    chat = _chat_with_semantic_plan(journal, _compound_research_write_intake())

    initial = chat.receive("research then write requiring confirmation", thread_id="thread-plan-run-blocked")
    result = chat.receive("/plan run", thread_id="thread-plan-run-blocked")

    assert initial.status == "needs_user_input"
    assert result.status == "failed"
    assert result.command_result is not None
    payload = result.command_result["result"]
    assert payload["decision"] == "run_blocked"
    assert payload["reason"] == "no_more_safe_executable_steps"
    assert [step["executed_node_id"] for step in payload["executed_steps"]] == ["node-1-retrieval_research"]
    decisions = journal.records(task_id=initial.task_id, kind="semantic_task_plan_decision")
    assert [record.data["decision"] for record in decisions] == ["approved", "blocked"]
    assert not any(record.data.get("name") == "workspace.write" for record in journal.records(kind="tool_call"))


def test_phase81_failed_plan_step_does_not_unlock_dependencies_on_next_run():
    journal = JournalStore.in_memory()
    fabric = fake_fabric({"semantic.intake": _multi_safe_with_finalizer_intake()}, journal=journal)
    agent = AgentRuntime(
        journal=journal,
        artifact_store=ArtifactStore.in_memory(),
        processor_fabric=fabric,
        retrieval_operator=RetrievalOperator(
            search_provider=FakeSearchProvider({}),
            fetch_provider=FakeFetchProvider({}),
        ),
    )
    chat = ChatRuntime(
        journal=journal,
        agent_runtime=agent,
        semantic_mode="model",
        turn_router_mode="fake",
    )

    initial = chat.receive("research, read workspace, then synthesize", thread_id="thread-plan-run-failed-dependency")
    first = chat.receive("/plan run", thread_id="thread-plan-run-failed-dependency")
    second = chat.receive("/plan run", thread_id="thread-plan-run-failed-dependency")
    shown = chat.receive("/plan", thread_id="thread-plan-run-failed-dependency")

    assert initial.status == "needs_user_input"
    assert first.command_result is not None
    assert first.command_result["decision"] == "run_paused"
    assert first.command_result["reason"] == "spawned_task_failed"
    assert first.command_result["executed_steps"][0]["executed_node_id"] == "node-1-retrieval_research"
    assert second.status == "failed"
    assert second.command_result is not None
    assert second.command_result["result"]["decision"] == "run_failed"
    assert second.command_result["result"]["reason"] == "missing_dependency_output"
    decisions = journal.records(task_id=initial.task_id, kind="semantic_task_plan_decision")
    assert [record.data["decision"] for record in decisions] == ["approved"]
    assert not any(record.data.get("name") == "workspace.search" for record in journal.records(kind="action"))
    assert not journal.records(task_id=initial.task_id, kind="semantic_task_plan_final_answer")
    progress = shown.command_result["result"]["progress"]
    assert [step["progress_status"] for step in progress["steps"]] == ["failed", "pending", "pending"]


def test_phase81_continue_without_unfinished_plan_still_asks_clarification():
    journal = JournalStore.in_memory()
    chat = ChatRuntime(journal=journal, agent_runtime=AgentRuntime(journal=journal))

    first = chat.receive("plain completed task", thread_id="thread-no-plan-continue")
    fabric = fake_fabric(
        {"chat.route": _chat_route("continue_plan", reasons=["semantic_continuation_without_state"])},
        journal=journal,
    )
    chat = ChatRuntime(
        journal=journal,
        agent_runtime=AgentRuntime(journal=journal, processor_fabric=fabric),
        turn_router_mode="model",
    )
    continued = chat.receive("carry the prior work forward", thread_id="thread-no-plan-continue")

    assert first.status == "completed"
    assert continued.route == "new_task"
    assert continued.status == "needs_user_input"


def test_phase81_chat_plan_approve_does_not_run_dependent_respond_without_evidence_context():
    journal = JournalStore.in_memory()
    chat = _chat_with_semantic_plan(
        journal,
        _dependent_synthesis_intake(),
        chat_routes=[
            _chat_route("new_task"),
            _chat_route("continue_plan"),
            _chat_route("continue_plan"),
        ],
    )

    initial = chat.receive("research then synthesize requiring confirmation", thread_id="thread-plan-dependent-respond")
    first = chat.receive("/plan approve", thread_id="thread-plan-dependent-respond")
    second = chat.receive("继续", thread_id="thread-plan-dependent-respond")

    assert initial.status == "needs_user_input"
    assert first.status == "completed"
    assert first.command_result is not None
    assert first.command_result["executed_node_id"] == "node-1-retrieval_research"
    assert second.status == "completed"
    assert second.route == "continue_plan"
    assert second.command_result is not None
    assert second.final_answer is not None
    decisions = journal.records(task_id=initial.task_id, kind="semantic_task_plan_decision")
    assert [record.data["decision"] for record in decisions] == ["approved"]
    action_task_ids = {record.task_id for record in journal.records(kind="action")}
    assert action_task_ids == {initial.task_id, first.command_result["spawned_task_id"]}
    child = journal.records(task_id=first.command_result["spawned_task_id"], kind="agent_final_answer")[-1].data
    assert second.final_answer["citation_refs"] == child["citation_refs"]
    assert second.final_answer["used_evidence"] == child["used_evidence"]
    assert "synthesize from the collected evidence" in second.answer
    final_records = journal.records(task_id=initial.task_id, kind="semantic_task_plan_final_answer")
    assert len(final_records) == 1
    shown = chat.receive("/plan", thread_id="thread-plan-dependent-respond")
    progress = shown.command_result["result"]["progress"]
    assert progress["finalized"] is True
    assert progress["final_answer_ref"] == final_records[0].record_id
    assert progress["steps"][0]["progress_status"] == "completed"
    assert progress["steps"][1]["progress_status"] == "pending"
    assert "finalized=True" in (shown.answer or "")
    summary = chat.receive("/summary", thread_id="thread-plan-dependent-respond")
    assert summary.summary is not None
    assert "synthesize from the collected evidence" in str(summary.summary["last_answer_preview"])
    repeated = chat.receive("继续", thread_id="thread-plan-dependent-respond")
    assert repeated.status == "needs_user_input"
    assert repeated.route == "new_task"
    assert repeated.command_result is None
    assert len(journal.records(task_id=initial.task_id, kind="semantic_task_plan_final_answer")) == 1


def test_phase81_chat_plan_finalize_fails_before_dependencies_complete():
    journal = JournalStore.in_memory()
    chat = _chat_with_semantic_plan(journal, _dependent_synthesis_intake())

    initial = chat.receive("research then synthesize requiring confirmation", thread_id="thread-plan-finalize-missing")
    final = chat.receive("/plan finalize", thread_id="thread-plan-finalize-missing")

    assert initial.status == "needs_user_input"
    assert final.status == "failed"
    assert final.command_result is not None
    assert final.command_result["result"]["reason"] == "missing_dependency_output"
    assert final.command_result["result"]["missing_nodes"] == ["node-1-retrieval_research"]
    assert not journal.records(task_id=initial.task_id, kind="semantic_task_plan_final_answer")


def _chat_with_semantic_plan(journal: JournalStore, response: dict, *, chat_routes: list[dict] | None = None) -> ChatRuntime:
    responses = {"semantic.intake": response}
    if chat_routes is not None:
        responses["chat.route"] = chat_routes
    fabric = fake_fabric(responses, journal=journal)
    agent = AgentRuntime(journal=journal, processor_fabric=fabric)
    return ChatRuntime(
        journal=journal,
        agent_runtime=agent,
        semantic_mode="model",
        turn_router_mode="model" if chat_routes is not None else "fake",
    )


def _chat_route(route: str, *, command: str | None = None, reasons: list[str] | None = None) -> dict:
    return {
        "route": route,
        "command": command,
        "target_task_id": None,
        "confidence": 0.97,
        "reasons": list(reasons or [f"fake_model_{route}"]),
    }


def _compound_research_write_intake() -> dict:
    return {
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
                "metadata": {},
            },
            {
                "kind": "workspace_write",
                "text": "write a local report after the research",
                "sequence_index": 2,
                "required_capabilities": ["workspace:write"],
                "risk": "write",
                "status": "needs_permission",
                "metadata": {},
            },
        ],
        "blocked_capabilities": ["workspace:write"],
        "warnings": ["model_detected_compound_task"],
        "response_hint": None,
        "clarification_question": "Confirm the ordered plan and write permission.",
    }


def _shell_only_intake() -> dict:
    return {
        "primary_intent": "direct_answer",
        "suggested_mode": "direct_answer",
        "compound": False,
        "requires_clarification": False,
        "intents": [
            {
                "kind": "direct_answer",
                "text": "execute a machine command",
                "sequence_index": 1,
                "required_capabilities": ["shell:exec"],
                "risk": "shell",
                "status": "blocked",
                "metadata": {},
            }
        ],
        "blocked_capabilities": [],
        "warnings": [],
        "response_hint": None,
        "clarification_question": None,
    }


def _multi_safe_read_after_research_intake() -> dict:
    return {
        "primary_intent": "retrieval_research",
        "suggested_mode": "clarify_first",
        "compound": True,
        "requires_clarification": True,
        "intents": [
            {
                "kind": "retrieval_research",
                "text": "research current API evidence",
                "sequence_index": 1,
                "required_capabilities": ["retrieval.run"],
                "risk": "read",
                "status": "ready",
                "metadata": {},
            },
            {
                "kind": "workspace_read",
                "text": "read README.md after the research",
                "sequence_index": 2,
                "required_capabilities": ["workspace.search", "file.read"],
                "risk": "read",
                "status": "ready",
                "metadata": {},
            },
        ],
        "blocked_capabilities": [],
        "warnings": ["model_detected_compound_task"],
        "response_hint": None,
        "clarification_question": "Confirm the ordered read-only plan.",
    }


def _dependent_synthesis_intake() -> dict:
    return {
        "primary_intent": "retrieval_research",
        "suggested_mode": "clarify_first",
        "compound": True,
        "requires_clarification": True,
        "intents": [
            {
                "kind": "retrieval_research",
                "text": "research current API evidence",
                "sequence_index": 1,
                "required_capabilities": ["retrieval.run"],
                "risk": "read",
                "status": "ready",
                "metadata": {},
            },
            {
                "kind": "synthesis",
                "text": "synthesize from the collected evidence",
                "sequence_index": 2,
                "required_capabilities": [],
                "risk": "none",
                "status": "ready",
                "metadata": {},
            },
        ],
        "blocked_capabilities": [],
        "warnings": ["model_detected_compound_task"],
        "response_hint": None,
        "clarification_question": "Confirm the ordered evidence and synthesis plan.",
    }


def _multi_safe_with_finalizer_intake() -> dict:
    return {
        "primary_intent": "retrieval_research",
        "suggested_mode": "clarify_first",
        "compound": True,
        "requires_clarification": True,
        "intents": [
            {
                "kind": "retrieval_research",
                "text": "research current API evidence",
                "sequence_index": 1,
                "required_capabilities": ["retrieval.run"],
                "risk": "read",
                "status": "ready",
                "metadata": {},
            },
            {
                "kind": "workspace_read",
                "text": "read README.md after the research",
                "sequence_index": 2,
                "required_capabilities": ["workspace.search", "file.read"],
                "risk": "read",
                "status": "ready",
                "metadata": {},
            },
            {
                "kind": "synthesis",
                "text": "synthesize from the completed read-only evidence",
                "sequence_index": 3,
                "required_capabilities": [],
                "risk": "none",
                "status": "ready",
                "metadata": {"depends_on": ["node-1-retrieval_research", "node-2-workspace_read"]},
            },
        ],
        "blocked_capabilities": [],
        "warnings": ["model_detected_compound_task"],
        "response_hint": None,
        "clarification_question": "Confirm the ordered read-only plan.",
    }
