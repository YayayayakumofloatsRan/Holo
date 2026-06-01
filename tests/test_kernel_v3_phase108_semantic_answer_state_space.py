from kernel_v3.agent import AgentRuntime
from kernel_v3.capabilities import semantic_capability_catalog
from kernel_v3.journal import JournalStore
from kernel_v3.processors.testing import fake_fabric


def test_phase108_semantic_answer_mode_is_first_class_and_toolless():
    journal = JournalStore.in_memory()

    result = AgentRuntime(journal=journal).run(
        "扮演一个初出茅庐的律师，你会怎么做",
        mode="semantic",
    )

    assert result.status == "completed"
    assert result.mode == "semantic_answer"
    assert result.final_answer is not None
    assert "广义语义任务" in result.final_answer["answer"]
    recipe = journal.records(task_id=result.task_id, kind="agent_recipe")[0].data
    assert recipe["recipe_id"] == "recipe-semantic-answer"
    assert recipe["allowed_tools"] == []
    assert recipe["finalizer"] == "semantic_observation"
    assert _action_names(journal, result.task_id) == ["respond"]


def test_phase108_model_intake_can_route_broad_safe_semantics_without_workspace_collapse():
    journal = JournalStore.in_memory()
    fabric = fake_fabric(
        {
            "semantic.intake": {
                "primary_intent": "professional_planning_roleplay",
                "suggested_mode": "semantic_answer",
                "compound": True,
                "requires_clarification": False,
                "intents": [
                    {
                        "kind": "roleplay",
                        "text": "回应时采用谨慎的初级律师口吻",
                        "sequence_index": 1,
                        "required_capabilities": ["roleplay.perform"],
                        "risk": "none",
                        "status": "ready",
                        "metadata": {
                            "domain": "legal",
                            "activity": "respond",
                            "resource": "conversation_turn",
                        },
                    },
                    {
                        "kind": "operations_planning",
                        "text": "说明面对新案件时会怎样拆解事实、证据和风险",
                        "sequence_index": 2,
                        "required_capabilities": ["operations.plan", "legal.information"],
                        "risk": "normal",
                        "status": "ready",
                        "metadata": {
                            "domain": "operations",
                            "activity": "plan",
                            "resource": "task_plan",
                        },
                    },
                    {
                        "kind": "communication_drafting",
                        "text": "用舒服的中文语气回复用户",
                        "sequence_index": 3,
                        "required_capabilities": ["communication.draft", "preference.apply"],
                        "risk": "none",
                        "status": "ready",
                        "metadata": {
                            "domain": "communication",
                            "activity": "write",
                            "resource": "message_draft",
                        },
                    },
                ],
                "blocked_capabilities": [],
                "warnings": [],
                "response_hint": None,
                "clarification_question": None,
            },
            "planner.propose": {
                "action_id": "act-semantic-model-1",
                "kind": "respond",
                "name": None,
                "description": "answer as a broad semantic task without tools",
                "payload": {
                    "text": "我会先确认事实和目标，再把问题拆成事实、法律问题、证据、风险和下一步沟通。"
                },
                "score": 0.91,
                "reasons": ["semantic_answer_state_profile"],
                "side_effect_class": "none",
            },
        },
        journal=journal,
    )

    result = AgentRuntime(journal=journal, processor_fabric=fabric).run(
        "扮演一个初出茅庐的律师，你会怎么做",
        mode="auto",
        semantic_mode="model",
        planner_mode="model",
    )

    assert result.status == "completed"
    assert result.mode == "semantic_answer"
    assert result.final_answer is not None
    assert "法律问题" in result.final_answer["answer"]
    assert _action_names(journal, result.task_id) == ["respond"]

    plan = journal.records(task_id=result.task_id, kind="semantic_task_plan")[0].data
    assert plan["selected_mode"] == "semantic_answer"
    assert all(step["tool_name"] is None for step in plan["steps"])
    assert all(step["action_kind"] == "respond" for step in plan["steps"])

    profile_record = journal.records(task_id=result.task_id, kind="agent_state_profile")[0].data
    summary = profile_record["summary"]
    assert {"legal", "operations", "communication"}.issubset(set(summary["domains"]))
    assert "workspace" not in summary["domains"]
    assert "semantic_answer" in semantic_capability_catalog()["modes"]

    context = journal.records(task_id=result.task_id, kind="context")[0].data["state"]
    directive = context["agent_runtime_directive"]
    assert directive["mode"] == "semantic_answer"
    assert directive["allowed_tools"] == []
    assert "state_space_rule" in directive
    assert context["capability_catalog"]["mode"] == "semantic_answer"


def test_phase108_planner_prompt_exposes_semantic_directive_to_model():
    journal = JournalStore.in_memory()
    fabric = fake_fabric(
        {
            "semantic.intake": {
                "primary_intent": "strategy_assessment",
                "suggested_mode": "semantic_answer",
                "compound": False,
                "requires_clarification": False,
                "intents": [
                    {
                        "kind": "strategy_assessment",
                        "text": "评估一个产品路线选择",
                        "sequence_index": 1,
                        "required_capabilities": ["strategy.assess", "product.analysis"],
                        "risk": "normal",
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
                "action_id": "act-strategy-1",
                "kind": "respond",
                "name": None,
                "description": "return a strategy frame",
                "payload": {"text": "我会从用户价值、风险、成本、速度和可逆性比较路线。"},
                "score": 0.88,
                "reasons": ["semantic_strategy"],
                "side_effect_class": "none",
            },
        },
        journal=journal,
    )

    result = AgentRuntime(journal=journal, processor_fabric=fabric).run(
        "评估一个产品路线选择",
        mode="auto",
        semantic_mode="model",
        planner_mode="model",
    )

    assert result.status == "completed"
    planner_requests = [
        record.data for record in journal.records(task_id=result.task_id, kind="processor_request")
        if record.data.get("task_type") == "planner.propose"
    ]
    assert planner_requests
    assert planner_requests[0]["prompt"]["chars"] > len(planner_requests[0]["prompt"]["preview"])
    assert planner_requests[0]["redaction"]["prompt"] == "preview_hash_only"
    state = journal.records(task_id=result.task_id, kind="context")[0].data["state"]
    assert state["agent_runtime_directive"]["mode"] == "semantic_answer"
    assert state["agent_runtime_directive"]["allowed_tools"] == []
    assert state["semantic_state_profile_summary"]["domains"] == ["conversation", "product"]


def _action_names(journal: JournalStore, task_id: str) -> list[str]:
    return [
        str(record.data.get("name") or record.data.get("kind"))
        for record in journal.records(task_id=task_id, kind="action")
    ]
