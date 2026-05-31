from kernel_v3.agent import AgentRuntime, build_task_execution_plan, task_graph_from_semantic, validate_task_graph
from kernel_v3.agent.contracts import SemanticIntake, TaskGraphProposal
from kernel_v3.journal import JournalStore
from kernel_v3.processors.testing import fake_fabric


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
