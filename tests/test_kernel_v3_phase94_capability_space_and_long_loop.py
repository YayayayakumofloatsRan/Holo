from pathlib import Path

from kernel_v3.agent import AgentRuntime, SemanticIntake, build_task_execution_plan, task_graph_from_semantic, validate_task_graph
from kernel_v3.capabilities import semantic_capability_catalog
from kernel_v3.context import ArtifactStore
from kernel_v3.journal import JournalStore
from kernel_v3.processors.testing import fake_fabric
from kernel_v3.research import FINANCE_FUNDAMENTALS_PROFILE_ID, finance_fundamentals_source_directory
from kernel_v3.retrieval import FakeFetchProvider, FakeSearchProvider, RetrievalOperator, SearchSource


def test_phase94_capability_catalog_exposes_broad_agent_state_space(tmp_path):
    (tmp_path / "README.md").write_text("capability catalog fixture", encoding="utf-8")
    journal = JournalStore.in_memory()
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
                        "text": "read README",
                        "sequence_index": 1,
                        "required_capabilities": ["workspace.search", "file.read"],
                        "risk": "read",
                        "status": "ready",
                        "metadata": {
                            "capability_args": {
                                "workspace.search": {"query": "capability catalog fixture"},
                                "file.read": {"path": "README.md"},
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

    result = AgentRuntime(journal=journal, processor_fabric=fabric, workspace_root=tmp_path).run(
        "read README",
        mode="auto",
        semantic_mode="model",
    )

    assert result.status == "completed"
    context = journal.records(task_id=result.task_id, kind="context")[0].data["state"]
    catalog = context["capability_catalog"]
    state_space = context["semantic_state_space"]
    families = set(catalog["families"])
    assert {
        "conversation",
        "workspace",
        "retrieval",
        "finance",
        "memory",
        "artifact",
        "data",
        "code",
        "project",
        "resident",
        "transport",
        "calendar",
        "system",
        "security",
    }.issubset(families)
    capability_ids = {item["capability_id"] for item in catalog["capabilities"]}
    assert {
        "workspace.file.write",
        "web.search",
        "web.crawl",
        "browser.page.open",
        "finance.fundamentals_research",
        "finance.market_news",
        "durable_memory.propose",
        "durable_memory.delete",
        "artifact.create",
        "data.table.analyze",
        "code.patch",
        "project.status",
        "resident.scheduler",
        "calendar.schedule",
        "transport.wechat",
        "credential.read",
        "device.input.control",
        "system.time",
        "shell.exec",
    }.issubset(capability_ids)
    assert "web.search" in catalog["not_configured"]
    assert "web.crawl" in catalog["planned"]
    assert "autonomy" in state_space["state_dimensions"]
    assert "world_model" in state_space["state_dimensions"]
    assert "resource_kind" in state_space["state_dimensions"]
    assert "authority" in state_space["state_dimensions"]
    assert "identity_boundary" in state_space["state_dimensions"]
    assert "transport" in state_space["families"]
    assert "security" in state_space["families"]


def test_phase94_semantic_capability_catalog_is_not_workspace_only():
    catalog = semantic_capability_catalog()

    families = catalog["families"]
    assert "finance" in families
    assert "retrieval" in families
    assert "memory" in families
    assert "artifact" in families
    assert "data" in families
    assert "code" in families
    assert "project" in families
    assert "resident" in families
    assert "transport" in families
    assert "calendar" in families
    assert "security" in families
    assert "system" in families
    assert "finance_fundamentals" in catalog["task_domains"]
    assert "data_analysis" in catalog["task_domains"]
    assert "calendar_or_reminder" in catalog["task_domains"]
    assert "credential_or_secret_boundary" in catalog["task_domains"]
    assert "network" in catalog["state_dimensions"]
    assert "artifacts" in catalog["state_dimensions"]
    assert "external_systems" in catalog["state_dimensions"]
    assert "resident" in catalog["state_dimensions"]
    assert "tooling" in catalog["state_dimensions"]
    assert "workspace_write" in catalog["modes"]
    assert "system_answer" in catalog["modes"]
    assert catalog["executable_tools_by_recipe"]["system_answer"] == ["system.time"]
    assert "calendar.schedule" in catalog["not_default_or_requires_configuration"]
    assert "device.input.control" in catalog["not_default_or_requires_configuration"]
    assert "execution_surface" in catalog["state_dimensions"]
    assert "intent_scope" in catalog["state_dimensions"]
    assert "output_contract" in catalog["state_dimensions"]
    assert "autonomy" in catalog["state_dimensions"]
    assert "world_model" in catalog["state_dimensions"]
    assert "resource_kind" in catalog["state_dimensions"]
    assert "authority" in catalog["state_dimensions"]
    assert "identity_boundary" in catalog["state_dimensions"]
    assert "communication_channel" in catalog["state_dimensions"]
    assert "semantic_slots" in catalog
    assert "document" in families
    assert "roleplay.perform" in families["conversation"]
    assert "web.research" in families["retrieval"]
    assert "finance.competitive_landscape" in families["finance"]
    assert "report_generation" in catalog["task_domains"]
    assert "long_running_monitoring" in catalog["task_domains"]
    assert "browser_navigation_boundary" in catalog["task_domains"]
    assert "database" in families
    assert "cloud" in families
    assert "workflow" in families
    assert "knowledge_base" in families
    assert "multimodal" in families
    assert "legal" in families
    assert "medical" in families
    assert "education" in families
    assert "creative" in families
    assert "communication" in families
    assert "operations" in families
    assert "product" in families
    assert "risk" in families
    assert "cybersecurity" in families
    assert "database_query" in catalog["task_domains"]
    assert "workflow_automation" in catalog["task_domains"]
    assert "portfolio_risk_research" in catalog["task_domains"]
    assert "communication_drafting" in catalog["task_domains"]
    assert "operations_planning" in catalog["task_domains"]
    assert "product_analysis" in catalog["task_domains"]
    assert "risk_compliance_review" in catalog["task_domains"]
    assert "cybersecurity_review" in catalog["task_domains"]
    assert "database.query" in catalog["not_default_or_requires_configuration"]
    assert "cloud.resource.inspect" in catalog["not_default_or_requires_configuration"]
    assert "workflow.automation.run" in catalog["not_default_or_requires_configuration"]
    assert "legal.research" in catalog["not_default_or_requires_configuration"]
    assert "medical.research" in catalog["not_default_or_requires_configuration"]
    assert "communication.send" in catalog["not_default_or_requires_configuration"]


def test_phase94_task_graph_nodes_preserve_broad_state_profiles():
    intake = SemanticIntake(
        intake_id="semantic-intake-1",
        goal="research a company, inspect database assumptions, and plan an automation",
        primary_intent="compound_research_operations",
        suggested_mode="retrieval_answer",
        compound=True,
        requires_clarification=False,
        intents=[
            {
                "kind": "finance_fundamentals",
                "text": "research company fundamentals",
                "sequence_index": 1,
                "required_capabilities": ["finance.fundamentals_research", "web.research"],
                "risk": "read",
                "status": "ready",
                "metadata": {"domain": "finance", "activity": "research"},
            },
            {
                "kind": "database_query",
                "text": "inspect valuation assumptions in the warehouse",
                "sequence_index": 2,
                "required_capabilities": ["database.query"],
                "risk": "read",
                "status": "ready",
                "metadata": {},
            },
            {
                "kind": "workflow_automation",
                "text": "plan a recurring report workflow",
                "sequence_index": 3,
                "required_capabilities": ["workflow.automation.plan"],
                "risk": "none",
                "status": "ready",
                "metadata": {},
            },
        ],
        blocked_capabilities=[],
        warnings=[],
        response_hint=None,
        clarification_question=None,
    )

    graph = task_graph_from_semantic(intake)

    profiles = [node["metadata"]["state_profile"] for node in graph.nodes]
    assert [profile["domain"] for profile in profiles] == ["finance", "database", "workflow"]
    assert "retrieval" in profiles[0]["execution_surface"]
    assert profiles[1]["route_class"] == "planned_or_not_configured_boundary"
    assert profiles[1]["permission_state"] == "planned"
    assert profiles[2]["route_class"] == "host_capability_or_response"
    assert {"finance", "retrieval", "database", "workflow"}.issubset(
        set(graph.metadata["state_profile_summary"]["domains"])
    )
    assert "workspace" not in graph.metadata["state_profile_summary"]["domains"]


def test_phase94_state_profile_values_match_declared_state_space():
    catalog = semantic_capability_catalog()
    dimensions = catalog["state_dimensions"]
    intake = SemanticIntake(
        intake_id="semantic-intake-1",
        goal="inspect database, cloud, images, credentials, and reminder boundaries",
        primary_intent="broad_boundary_audit",
        suggested_mode="direct_answer",
        compound=True,
        requires_clarification=False,
        intents=[
            {
                "kind": "database_query",
                "text": "inspect approved database assumptions",
                "sequence_index": 1,
                "required_capabilities": ["database.query"],
                "risk": "read",
                "status": "ready",
                "metadata": {},
            },
            {
                "kind": "cloud_resource_review",
                "text": "inspect cloud resource state",
                "sequence_index": 2,
                "required_capabilities": ["cloud.resource.inspect"],
                "risk": "read",
                "status": "ready",
                "metadata": {},
            },
            {
                "kind": "multimodal_document_review",
                "text": "analyze an uploaded document image",
                "sequence_index": 3,
                "required_capabilities": ["multimodal.image.analyze"],
                "risk": "read",
                "status": "ready",
                "metadata": {},
            },
            {
                "kind": "credential_boundary",
                "text": "read account credentials",
                "sequence_index": 4,
                "required_capabilities": ["credential.read"],
                "risk": "credential",
                "status": "ready",
                "metadata": {},
            },
            {
                "kind": "calendar_or_reminder",
                "text": "schedule a reminder",
                "sequence_index": 5,
                "required_capabilities": ["calendar.schedule"],
                "risk": "write",
                "status": "ready",
                "metadata": {},
            },
        ],
        blocked_capabilities=[],
        warnings=[],
        response_hint=None,
        clarification_question=None,
    )

    graph = task_graph_from_semantic(intake)
    profiles = [node["metadata"]["state_profile"] for node in graph.nodes]

    assert {"database", "cloud", "multimodal", "security", "calendar"}.issubset(
        {profile["domain"] for profile in profiles}
    )
    for profile in profiles:
        assert profile["execution_surface"] in dimensions["execution_surface"]
        assert profile["resource"] in dimensions["resource_kind"]
        assert profile["permission_state"] in dimensions["permissions"]
        assert profile["evidence_posture"] in dimensions["evidence"]
        assert profile["output_contract"] in dimensions["output_contract"]
        assert profile["autonomy"] in dimensions["autonomy"]
        assert profile["risk_posture"] in dimensions["risk"]
        assert profile["route_class"] in dimensions["route_class"]
        for axis, value in profile["state_axes"].items():
            assert axis in dimensions
            assert value in dimensions[axis]


def test_phase94_state_profiles_cover_hermes_level_non_workspace_domains():
    catalog = semantic_capability_catalog()
    dimensions = catalog["state_dimensions"]
    intake = SemanticIntake(
        intake_id="semantic-intake-1",
        goal="cover professional, communication, operations, product, and risk domains",
        primary_intent="broad_professional_work",
        suggested_mode="direct_answer",
        compound=True,
        requires_clarification=False,
        intents=[
            {
                "kind": "legal_research",
                "text": "research a regulation",
                "sequence_index": 1,
                "required_capabilities": ["legal.research"],
                "risk": "read",
                "status": "ready",
                "metadata": {"evidence_required": True, "citations_required": True},
            },
            {
                "kind": "medical_information",
                "text": "explain a general health concept",
                "sequence_index": 2,
                "required_capabilities": ["medical.information"],
                "risk": "normal",
                "status": "ready",
                "metadata": {},
            },
            {
                "kind": "education_tutoring",
                "text": "teach a topic",
                "sequence_index": 3,
                "required_capabilities": ["education.tutor"],
                "risk": "none",
                "status": "ready",
                "metadata": {},
            },
            {
                "kind": "communication_drafting",
                "text": "draft a customer update",
                "sequence_index": 4,
                "required_capabilities": ["communication.draft"],
                "risk": "none",
                "status": "ready",
                "metadata": {},
            },
            {
                "kind": "operations_planning",
                "text": "plan an operations runbook",
                "sequence_index": 5,
                "required_capabilities": ["operations.plan"],
                "risk": "none",
                "status": "ready",
                "metadata": {},
            },
            {
                "kind": "product_analysis",
                "text": "analyze a product workflow",
                "sequence_index": 6,
                "required_capabilities": ["product.analysis"],
                "risk": "none",
                "status": "ready",
                "metadata": {},
            },
            {
                "kind": "risk_compliance_review",
                "text": "review controls and risks",
                "sequence_index": 7,
                "required_capabilities": ["risk.compliance_review"],
                "risk": "normal",
                "status": "ready",
                "metadata": {},
            },
            {
                "kind": "cybersecurity_review",
                "text": "review a defensive security checklist",
                "sequence_index": 8,
                "required_capabilities": ["cybersecurity.review"],
                "risk": "normal",
                "status": "ready",
                "metadata": {},
            },
        ],
        blocked_capabilities=[],
        warnings=[],
        response_hint=None,
        clarification_question=None,
    )

    graph = task_graph_from_semantic(intake)
    profiles = [node["metadata"]["state_profile"] for node in graph.nodes]
    summary = graph.metadata["state_profile_summary"]

    assert {
        "legal",
        "medical",
        "education",
        "communication",
        "operations",
        "product",
        "risk",
        "cybersecurity",
    }.issubset(set(summary["domains"]))
    assert "workspace" not in summary["domains"]
    assert "state_axes" in summary
    assert "legal_research" in summary["state_axes"]["domain_profile"]
    assert "medical_information" in summary["state_axes"]["domain_profile"]
    assert "education_tutoring" in summary["state_axes"]["domain_profile"]
    assert "communication_drafting" in summary["state_axes"]["domain_profile"]
    assert "operations_planning" in summary["state_axes"]["domain_profile"]
    assert "product_analysis" in summary["state_axes"]["domain_profile"]
    assert "risk_compliance_review" in summary["state_axes"]["domain_profile"]
    assert "cybersecurity_review" in summary["state_axes"]["domain_profile"]
    assert "retrieval" in summary["state_axes"]["execution_surface"]
    assert "workflow_engine" in summary["state_axes"]["execution_surface"]
    assert "message_draft" in summary["state_axes"]["resource_kind"]
    assert "professional_domain_role" in summary["state_axes"]["identity_boundary"]
    for profile in profiles:
        for axis, value in profile["state_axes"].items():
            assert axis in dimensions
            assert value in dimensions[axis]


def test_phase94_state_profiles_include_operating_state_beyond_resource_mode():
    catalog = semantic_capability_catalog()
    dimensions = catalog["state_dimensions"]
    for axis in {
        "goal_structure",
        "dependency_state",
        "commitment_state",
        "preference_state",
        "memory_scope",
        "planning_depth",
        "operation_runtime",
        "quality_bar",
        "interruption_policy",
    }:
        assert axis in dimensions

    intake = SemanticIntake(
        intake_id="semantic-intake-1",
        goal="roleplay, plan finance research, keep a resident monitor, and apply my style preference",
        primary_intent="broad_operating_state",
        suggested_mode="direct_answer",
        compound=True,
        requires_clarification=False,
        intents=[
            {
                "kind": "roleplay",
                "text": "speak as Jarvis in this thread",
                "sequence_index": 1,
                "required_capabilities": ["roleplay.perform"],
                "risk": "none",
                "status": "ready",
                "metadata": {},
            },
            {
                "kind": "finance_fundamentals_research",
                "text": "research fundamentals using primary sources",
                "sequence_index": 2,
                "required_capabilities": ["finance.fundamentals_research", "web.research"],
                "risk": "read",
                "status": "ready",
                "metadata": {},
            },
            {
                "kind": "resident_monitor",
                "text": "monitor a future queue for updates",
                "sequence_index": 3,
                "required_capabilities": ["resident.scheduler"],
                "risk": "none",
                "status": "ready",
                "metadata": {},
            },
            {
                "kind": "preference_application",
                "text": "apply the user's concise Chinese preference",
                "sequence_index": 4,
                "required_capabilities": ["preference.apply"],
                "risk": "none",
                "status": "ready",
                "metadata": {},
            },
            {
                "kind": "device_control_boundary",
                "text": "move the user's mouse",
                "sequence_index": 5,
                "required_capabilities": ["device.input.control"],
                "risk": "destructive",
                "status": "ready",
                "metadata": {},
            },
        ],
        blocked_capabilities=[],
        warnings=[],
        response_hint=None,
        clarification_question=None,
    )

    graph = task_graph_from_semantic(intake)
    profiles = [node["metadata"]["state_profile"] for node in graph.nodes]
    by_kind = {profile["intent_kind"]: profile["state_axes"] for profile in profiles}

    assert by_kind["roleplay"]["identity_boundary"] == "roleplay_persona"
    assert by_kind["finance_fundamentals_research"]["goal_structure"] == "open_ended"
    assert by_kind["finance_fundamentals_research"]["quality_bar"] == "regulated_domain"
    assert by_kind["finance_fundamentals_research"]["dependency_state"] == "depends_on_external_data"
    assert by_kind["resident_monitor"]["goal_structure"] == "background_monitor"
    assert by_kind["resident_monitor"]["operation_runtime"] == "resident"
    assert by_kind["preference_application"]["preference_state"] == "thread_preference"
    assert by_kind["device_control_boundary"]["dependency_state"] == "depends_on_permission"
    assert by_kind["device_control_boundary"]["interruption_policy"] == "operator_approval_required"
    summary_axes = graph.metadata["state_profile_summary"]["state_axes"]
    assert {
        "open_ended",
        "background_monitor",
    }.issubset(set(summary_axes["goal_structure"]))
    assert {
        "regulated_domain",
        "standard",
    }.issubset(set(summary_axes["quality_bar"]))

    for profile in profiles:
        for axis, value in profile["state_axes"].items():
            assert axis in dimensions
            assert value in dimensions[axis]


def test_phase94_finance_intake_without_payload_gets_structured_retrieval_subgoals():
    intake = SemanticIntake(
        intake_id="semantic-intake-finance-default-plan",
        goal="检索一下APPLE INC的市盈率、股价、基本面信息等等",
        primary_intent="finance_fundamentals_research",
        suggested_mode="retrieval_answer",
        compound=False,
        requires_clarification=False,
        intents=[
            {
                "kind": "finance_fundamentals_research",
                "text": "APPLE INC 市盈率、股价、基本面信息",
                "sequence_index": 1,
                "required_capabilities": ["finance.fundamentals_research"],
                "risk": "read",
                "status": "ready",
                "metadata": {},
            }
        ],
        blocked_capabilities=[],
        warnings=[],
        response_hint=None,
        clarification_question=None,
    )

    graph = task_graph_from_semantic(intake)
    plan = build_task_execution_plan(graph, validate_task_graph(graph))
    step = plan.steps[0]
    payloads = step["metadata"]["capability_args"]["retrieval.run"]

    assert step["tool_name"] == "retrieval.run"
    assert len(payloads) >= 3
    queries = " ".join(payload["query"] for payload in payloads)
    metadata = [payload["metadata"] for payload in payloads]
    assert "SEC EDGAR" in queries
    assert "PE ratio" in queries
    assert all(item["research_profile"] == FINANCE_FUNDAMENTALS_PROFILE_ID for item in metadata)
    assert any(item["source_authority_requirement"] == "primary" for item in metadata)
    assert any(item["research_task_kind"] == "market_data" for item in metadata)
    assert any(item["search_strategy"] == "structured" for item in metadata)


def test_phase94_agent_context_exposes_state_profile_summary_to_planner():
    journal = JournalStore.in_memory()
    fabric = fake_fabric(
        {
            "semantic.intake": {
                "primary_intent": "knowledge_base_maintenance",
                "suggested_mode": "direct_answer",
                "compound": False,
                "requires_clarification": False,
                "intents": [
                    {
                        "kind": "knowledge_base_maintenance",
                        "text": "draft a maintenance plan for a knowledge base",
                        "sequence_index": 1,
                        "required_capabilities": ["workflow.automation.plan", "knowledge_base.maintain"],
                        "risk": "write",
                        "status": "ready",
                        "metadata": {"activity": "write"},
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
        "给知识库维护流程做一个自动化规划",
        mode="auto",
        semantic_mode="model",
    )

    assert result.status == "needs_user_input"
    context = journal.records(task_id=result.task_id, kind="context")[0].data["state"]
    summary = context["agent_runtime_directive"]["semantic_state_profile_summary"]
    assert summary["domains"] == ["workflow", "knowledge_base"]
    assert "planned_or_not_configured_boundary" in summary["route_classes"]
    plan = journal.records(task_id=result.task_id, kind="semantic_task_plan")[0].data
    profile = plan["steps"][0]["metadata"]["node_metadata"]["state_profile"]
    assert profile["resource"] == "queue_message"
    assert profile["execution_surface"] == "resident_queue"


def test_phase94_agent_journals_runtime_state_profile_projection():
    journal = JournalStore.in_memory()
    fabric = fake_fabric(
        {
            "semantic.intake": {
                "primary_intent": "operator_boundary_plan",
                "suggested_mode": "direct_answer",
                "compound": True,
                "requires_clarification": False,
                "intents": [
                    {
                        "kind": "database_query",
                        "text": "inspect valuation assumptions in a database",
                        "sequence_index": 1,
                        "required_capabilities": ["database.query"],
                        "risk": "read",
                        "status": "ready",
                        "metadata": {},
                    },
                    {
                        "kind": "cloud_resource_review",
                        "text": "inspect cloud resource inventory",
                        "sequence_index": 2,
                        "required_capabilities": ["cloud.resource.inspect"],
                        "risk": "read",
                        "status": "ready",
                        "metadata": {},
                    },
                    {
                        "kind": "knowledge_base_maintenance",
                        "text": "plan a knowledge-base maintenance workflow",
                        "sequence_index": 3,
                        "required_capabilities": ["workflow.automation.plan", "knowledge_base.maintain"],
                        "risk": "write",
                        "status": "ready",
                        "metadata": {},
                    },
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
        "检查数据库、云资源，并规划知识库维护",
        mode="auto",
        semantic_mode="model",
    )

    assert result.status == "needs_user_input"
    context = journal.records(task_id=result.task_id, kind="context")[0].data["state"]
    assert "semantic_state_profiles" in context
    assert "semantic_state_profile_summary" in context
    assert {"database", "cloud", "workflow", "knowledge_base"}.issubset(
        set(context["semantic_state_profile_summary"]["domains"])
    )
    profile_record = journal.records(task_id=result.task_id, kind="agent_state_profile")[0].data
    assert profile_record["summary"] == context["semantic_state_profile_summary"]
    assert len(profile_record["profiles"]) == 3
    assert {profile["execution_surface"] for profile in profile_record["profiles"]} != {"workspace"}


def test_phase94_broad_direct_capabilities_do_not_collapse_to_workspace():
    journal = JournalStore.in_memory()
    fabric = fake_fabric(
        {
            "semantic.intake": {
                "primary_intent": "roleplay",
                "suggested_mode": "direct_answer",
                "compound": False,
                "requires_clarification": False,
                "intents": [
                    {
                        "kind": "roleplay",
                        "text": "扮演一个初出茅庐的律师，说明你会怎么做",
                        "sequence_index": 1,
                        "required_capabilities": ["roleplay.perform", "conversation.respond"],
                        "risk": "none",
                        "status": "ready",
                        "metadata": {"persona": "junior_lawyer"},
                    }
                ],
                "blocked_capabilities": [],
                "warnings": [],
                "response_hint": "我会先确认事实、识别法律问题、列证据清单，再说明我不能替代执业律师意见。",
                "clarification_question": None,
            }
        },
        journal=journal,
    )

    result = AgentRuntime(journal=journal, processor_fabric=fabric).run(
        "扮演一个初出茅庐的律师，你会怎么做",
        mode="auto",
        semantic_mode="model",
    )

    assert result.status == "completed"
    graph = journal.records(task_id=result.task_id, kind="semantic_task_graph")[0].data
    assert graph["validation"]["status"] == "ready"
    plan = journal.records(task_id=result.task_id, kind="semantic_task_plan")[0].data
    assert plan["selected_mode"] == "direct_answer"
    assert plan["steps"][0]["kind"] == "roleplay"
    assert plan["steps"][0]["tool_name"] is None
    assert plan["steps"][0]["metadata"]["capability_plan"]["action_family"] == "host_capability"


def test_phase94_web_and_market_news_capabilities_route_to_retrieval_not_workspace():
    journal = JournalStore.in_memory()
    query = "今天的市场热点新闻"
    fabric = fake_fabric(
        {
            "semantic.intake": {
                "primary_intent": "market_news_research",
                "suggested_mode": "retrieval_answer",
                "compound": False,
                "requires_clarification": False,
                "intents": [
                    {
                        "kind": "market_news_research",
                        "text": query,
                        "sequence_index": 1,
                        "required_capabilities": ["web.research", "finance.market_news"],
                        "risk": "read",
                        "status": "ready",
                        "metadata": {
                            "evidence_required": True,
                            "citations_required": True,
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
    operator = RetrievalOperator(
        search_provider=FakeSearchProvider(
            {
                query: [
                    _source(
                        "market-news-source",
                        "https://www.reuters.com/site-search/?query=market%20news",
                        "今天的市场热点新闻",
                        "今天的市场热点新闻包括利率、股票和大宗商品。",
                    )
                ]
            }
        ),
        fetch_provider=FakeFetchProvider(
            {
                "https://www.reuters.com/site-search/?query=market%20news": (
                    "今天的市场热点新闻包括利率、股票和大宗商品，提供市场热点新闻的可引用证据。"
                )
            }
        ),
    )

    result = AgentRuntime(
        journal=journal,
        artifact_store=ArtifactStore.in_memory(),
        processor_fabric=fabric,
        retrieval_operator=operator,
    ).run(
        "搜索一下今天的热点新闻",
        mode="auto",
        semantic_mode="model",
    )

    assert result.status == "completed"
    assert result.mode == "retrieval_answer"
    graph = journal.records(task_id=result.task_id, kind="semantic_task_graph")[0].data
    assert graph["validation"]["status"] == "ready"
    plan = journal.records(task_id=result.task_id, kind="semantic_task_plan")[0].data
    assert plan["selected_mode"] == "retrieval_answer"
    assert plan["steps"][0]["tool_name"] == "retrieval.run"
    assert plan["steps"][0]["metadata"]["capability_plan"]["tools"] == ["retrieval.run"]
    actions = journal.records(task_id=result.task_id, kind="action")
    assert [record.data["name"] for record in actions] == ["retrieval.run"]
    assert actions[0].data["payload"]["query"] == query
    assert result.final_answer is not None
    assert result.final_answer["citation_refs"]


def test_phase94_dangerous_device_capability_remains_a_host_boundary():
    journal = JournalStore.in_memory()
    fabric = fake_fabric(
        {
            "semantic.intake": {
                "primary_intent": "device_control_boundary",
                "suggested_mode": "direct_answer",
                "compound": False,
                "requires_clarification": False,
                "intents": [
                    {
                        "kind": "device_control_boundary",
                        "text": "控制一下我的鼠标",
                        "sequence_index": 1,
                        "required_capabilities": ["device.input.control"],
                        "risk": "destructive",
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
        "控制一下我的鼠标",
        mode="auto",
        semantic_mode="model",
    )

    assert result.status == "needs_user_input"
    graph = journal.records(task_id=result.task_id, kind="semantic_task_graph")[0].data
    assert graph["validation"]["status"] == "needs_user_confirmation"
    assert graph["validation"]["blocked_capabilities"] == ["device.input.control"]
    plan = journal.records(task_id=result.task_id, kind="semantic_task_plan")[0].data
    assert plan["steps"][0]["status"] == "blocked"
    assert plan["steps"][0]["tool_name"] is None


def test_phase94_non_workspace_safe_capabilities_do_not_force_clarification():
    journal = JournalStore.in_memory()
    fabric = fake_fabric(
        {
            "semantic.intake": {
                "primary_intent": "artifact_summary",
                "suggested_mode": "direct_answer",
                "compound": False,
                "requires_clarification": False,
                "intents": [
                    {
                        "kind": "artifact_summary",
                        "text": "summarize current project status as a response artifact",
                        "sequence_index": 1,
                        "required_capabilities": ["artifact.create", "project.status"],
                        "risk": "none",
                        "status": "ready",
                        "metadata": {"format": "brief_status"},
                    }
                ],
                "blocked_capabilities": [],
                "warnings": [],
                "response_hint": "可以基于当前 journal/context 做简要状态汇报。",
                "clarification_question": None,
            }
        },
        journal=journal,
    )

    result = AgentRuntime(journal=journal, processor_fabric=fabric).run(
        "汇报当前项目状态",
        mode="auto",
        semantic_mode="model",
    )

    assert result.status == "completed"
    graph = journal.records(task_id=result.task_id, kind="semantic_task_graph")[0].data
    assert graph["validation"]["status"] == "ready"
    assert graph["validation"]["blocked_capabilities"] == []
    plan = journal.records(task_id=result.task_id, kind="semantic_task_plan")[0].data
    assert plan["selected_mode"] == "direct_answer"


def test_phase94_planned_broad_capability_is_not_treated_as_executable():
    journal = JournalStore.in_memory()
    fabric = fake_fabric(
        {
            "semantic.intake": {
                "primary_intent": "calendar_or_reminder",
                "suggested_mode": "direct_answer",
                "compound": False,
                "requires_clarification": False,
                "intents": [
                    {
                        "kind": "calendar_or_reminder",
                        "text": "schedule a reminder",
                        "sequence_index": 1,
                        "required_capabilities": ["calendar.schedule"],
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
        "明天提醒我开会",
        mode="auto",
        semantic_mode="model",
    )

    assert result.status == "needs_user_input"
    graph = journal.records(task_id=result.task_id, kind="semantic_task_graph")[0].data
    assert graph["validation"]["status"] == "needs_user_confirmation"
    assert graph["validation"]["blocked_capabilities"] == ["calendar.schedule"]
    plan = journal.records(task_id=result.task_id, kind="semantic_task_plan")[0].data
    assert plan["steps"][0]["status"] == "blocked"
    assert all(record.data["kind"] == "ask_user" for record in journal.records(task_id=result.task_id, kind="action"))


def test_phase94_agent_executes_system_time_as_non_workspace_capability():
    journal = JournalStore.in_memory()
    fabric = fake_fabric(
        {
            "semantic.intake": {
                "primary_intent": "system_time",
                "suggested_mode": "system_answer",
                "compound": False,
                "requires_clarification": False,
                "intents": [
                    {
                        "kind": "system_time",
                        "text": "current time in UTC",
                        "sequence_index": 1,
                        "required_capabilities": ["system.time"],
                        "risk": "read",
                        "status": "ready",
                        "metadata": {
                            "capability_args": {
                                "system.time": {"timezone": "UTC"},
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

    result = AgentRuntime(journal=journal, processor_fabric=fabric).run(
        "现在 UTC 是几点？",
        mode="auto",
        semantic_mode="model",
    )

    assert result.status == "completed"
    assert result.mode == "system_answer"
    actions = journal.records(task_id=result.task_id, kind="action")
    assert [record.data["name"] for record in actions] == ["system.time"]
    observation = journal.records(task_id=result.task_id, kind="observation")[0]
    assert observation.data["source"] == "tool:system.time"
    assert observation.data["content"]["timezone"] == "UTC"
    progress = journal.records(task_id=result.task_id, kind="progress_assessment")[0]
    assert progress.data["progress_type"] == "new_system_observation"
    assert "UTC" in result.final_answer["answer"]


def test_phase94_system_environment_is_safe_context_not_time_tool():
    journal = JournalStore.in_memory()
    fabric = fake_fabric(
        {
            "semantic.intake": {
                "primary_intent": "system_state_query",
                "suggested_mode": "semantic_answer",
                "compound": False,
                "requires_clarification": False,
                "intents": [
                    {
                        "kind": "system_state_query",
                        "text": "current thread information",
                        "sequence_index": 1,
                        "required_capabilities": ["system.environment"],
                        "risk": "none",
                        "status": "ready",
                        "metadata": {
                            "domain": "system_observation",
                            "resource": "thread_information",
                        },
                    }
                ],
                "blocked_capabilities": [],
                "warnings": [],
                "response_hint": None,
                "clarification_question": None,
            },
            "planner.propose": {
                "action_id": "act-thread-state",
                "kind": "respond",
                "name": None,
                "description": "answer from host-provided thread context",
                "payload": {"text": "当前所在 thread 是 thread-env。"},
                "score": 0.9,
                "reasons": ["thread_id is already present in host context"],
                "side_effect_class": "none",
            },
            "evaluator.assess": {
                "status": "final_answer_ready",
                "answer": "当前所在 thread 是 thread-env。",
                "stop_reason": "task_completed",
                "missing_evidence": [],
            },
        },
        journal=journal,
    )

    result = AgentRuntime(journal=journal, processor_fabric=fabric).run(
        "说明你现在在哪个 thread",
        thread_id="thread-env",
        mode="auto",
        semantic_mode="model",
        planner_mode="model",
        evaluator_mode="model",
    )

    assert result.status == "completed"
    assert result.mode == "semantic_answer"
    assert result.final_answer is not None
    assert result.final_answer["answer"] == "当前所在 thread 是 thread-env。"
    graph = journal.records(task_id=result.task_id, kind="semantic_task_graph")[0].data
    assert graph["validation"]["status"] == "ready"
    assert graph["validation"]["blocked_capabilities"] == []
    plan = journal.records(task_id=result.task_id, kind="semantic_task_plan")[0].data
    assert plan["selected_mode"] == "semantic_answer"
    assert plan["steps"][0]["tool_name"] is None
    actions = journal.records(task_id=result.task_id, kind="action")
    assert [(record.data["kind"], record.data["name"]) for record in actions] == [("respond", None)]
    assert not journal.records(task_id=result.task_id, kind="system_time")


def test_phase94_agent_can_execute_more_than_ten_planned_loop_actions(tmp_path):
    for index in range(12):
        path = tmp_path / "docs" / f"part-{index:02d}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"long-loop-doc-{index:02d}: evidence shard {index}\n", encoding="utf-8")
    journal = JournalStore.in_memory()
    intents = []
    for index in range(12):
        intents.append(
            {
                "kind": "workspace_read",
                "text": f"read evidence shard {index}",
                "sequence_index": index + 1,
                "required_capabilities": ["file.read"],
                "risk": "read",
                "status": "ready",
                "metadata": {
                    "capability_args": {"file.read": {"path": f"docs/part-{index:02d}.md"}},
                    "success_criteria": [f"include shard {index}"],
                },
            }
        )
    fabric = fake_fabric(
        {
            "semantic.intake": {
                "primary_intent": "multi_step_workspace_review",
                "suggested_mode": "workspace_answer",
                "compound": True,
                "requires_clarification": False,
                "intents": intents,
                "blocked_capabilities": [],
                "warnings": [],
                "response_hint": None,
                "clarification_question": None,
            }
        },
        journal=journal,
    )

    result = AgentRuntime(journal=journal, processor_fabric=fabric, workspace_root=tmp_path).run(
        "read all twelve evidence shards and summarize",
        mode="auto",
        semantic_mode="model",
    )

    assert result.status == "completed"
    actions = journal.records(task_id=result.task_id, kind="action")
    assert len(actions) == 12
    assert [record.data["name"] for record in actions] == ["file.read"] * 12
    assert len(journal.records(task_id=result.task_id, kind="observation")) == 12
    assert len(journal.records(task_id=result.task_id, kind="agent_work_plan")) == 1
    updates = journal.records(task_id=result.task_id, kind="agent_work_plan_update")
    assert len(updates) == 12
    assert updates[-1].data["status"] == "complete"
    decisions = journal.records(task_id=result.task_id, kind="termination_decision")
    assert len(decisions) == 12
    assert [record.data["decision"] for record in decisions[:-1]] == ["continue"] * 11
    assert decisions[-1].data["decision"] == "final_answer"
    assert result.final_answer is not None
    assert len(result.final_answer["citation_refs"]) == 12


def test_phase94_agent_expands_list_capability_args_into_multiple_actions(tmp_path):
    for index in range(11):
        path = tmp_path / "docs" / f"group-{index:02d}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"grouped-live-shape-{index:02d}\n", encoding="utf-8")
    journal = JournalStore.in_memory()
    fabric = fake_fabric(
        {
            "semantic.intake": {
                "primary_intent": "workspace_read_group",
                "suggested_mode": "workspace_answer",
                "compound": True,
                "requires_clarification": False,
                "intents": [
                    {
                        "kind": "workspace_read_group",
                        "text": "read grouped files",
                        "sequence_index": 1,
                        "required_capabilities": ["file.read"],
                        "risk": "read",
                        "status": "ready",
                        "metadata": {
                            "capability_args": {
                                "file.read": [
                                    {"path": f"docs/group-{index:02d}.md"}
                                    for index in range(11)
                                ]
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

    result = AgentRuntime(journal=journal, processor_fabric=fabric, workspace_root=tmp_path).run(
        "read grouped files",
        mode="auto",
        semantic_mode="model",
    )

    assert result.status == "completed"
    actions = journal.records(task_id=result.task_id, kind="action")
    assert len(actions) == 11
    assert actions[0].data["payload"]["path"] == "docs/group-00.md"
    assert actions[-1].data["payload"]["path"] == "docs/group-10.md"
    assert journal.records(task_id=result.task_id, kind="agent_work_plan_update")[-1].data["status"] == "complete"


def test_phase94_model_planner_can_drive_more_than_ten_dynamic_loop_actions(tmp_path):
    files = {}
    planner_actions = []
    evaluator_feedback = []
    for index in range(11):
        path = f"docs/model-loop-{index:02d}.md"
        files[path] = f"model-dynamic-loop-{index:02d}: evidence shard {index}\n"
        planner_actions.append(
            {
                "action_id": f"act-model-dynamic-read-{index:02d}",
                "kind": "tool",
                "name": "file.read",
                "description": f"read model-selected shard {index}",
                "payload": {"path": path},
                "score": 0.9,
                "reasons": ["dynamic model planner selected next file"],
                "side_effect_class": "read",
            }
        )
        evaluator_feedback.append(
            {
                "status": "continue" if index < 10 else "final_answer_ready",
                "answer": None,
                "stop_reason": None if index < 10 else "completed",
                "missing_evidence": ["remaining_plan_actions"] if index < 10 else [],
            }
        )
    journal = JournalStore.in_memory()
    fabric = fake_fabric(
        {
            "semantic.intake": {
                "primary_intent": "model_dynamic_workspace_review",
                "suggested_mode": "workspace_answer",
                "compound": False,
                "requires_clarification": False,
                "intents": [
                    {
                        "kind": "model_dynamic_workspace_review",
                        "text": "review all model-selected evidence shards",
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
            },
            "planner.propose": planner_actions,
            "evaluator.assess": evaluator_feedback,
        },
        journal=journal,
    )

    result = AgentRuntime(
        journal=journal,
        processor_fabric=fabric,
        workspace_files=files,
    ).run(
        "use model planning to inspect all evidence shards",
        mode="auto",
        semantic_mode="model",
        planner_mode="model",
        evaluator_mode="model",
        execution_metadata={
            "agent_loop": {
                "max_steps": 13,
                "max_tool_calls": 12,
                "max_total_artifact_bytes": 2_000_000,
            }
        },
    )

    assert result.status == "completed"
    actions = journal.records(task_id=result.task_id, kind="action")
    assert len(actions) == 11
    assert [record.data["name"] for record in actions] == ["file.read"] * 11
    assert len(journal.records(task_id=result.task_id, kind="processor_request")) >= 22
    work_plans = journal.records(task_id=result.task_id, kind="agent_work_plan")
    assert work_plans[0].data["planner_mode"] == "model"
    assert work_plans[0].data["strategy"] == "dynamic_replan_each_iteration"
    updates = journal.records(task_id=result.task_id, kind="agent_work_plan_update")
    assert len(updates) == 11
    assert updates[0].data["feedback_status"] is None
    assert updates[-1].data["revision"] == 11
    assert updates[-1].data["selected_action"]["name"] == "file.read"
    decisions = journal.records(task_id=result.task_id, kind="termination_decision")
    assert [record.data["decision"] for record in decisions[:-1]] == ["continue"] * 10
    assert decisions[-1].data["decision"] == "final_answer"
    assert len(result.final_answer["citation_refs"]) == 11


def test_phase94_finance_source_directory_is_structured_and_context_injected(tmp_path):
    directory = finance_fundamentals_source_directory()
    source_ids = {entry.source_id for entry in directory}
    assert {
        "finance-sec-edgar-filings",
        "finance-sec-companyfacts",
        "finance-sec-company-tickers",
        "finance-sec-edgar-archives",
        "finance-sec-financial-statement-data-sets",
        "finance-company-investor-relations",
        "finance-us-official-statistics",
        "finance-china-exchange-disclosures",
        "finance-hkex-disclosures",
        "finance-uk-companies-house-filings",
        "finance-canada-sedar-plus-filings",
        "finance-asx-announcements",
        "finance-japan-edinet-filings",
        "finance-sgx-announcements",
        "finance-global-official-statistics",
        "finance-market-data-secondary",
    }.issubset(source_ids)
    assert all(entry.allowed_hosts for entry in directory)
    assert all(entry.query_hints for entry in directory)
    assert all(entry.required_identifiers for entry in directory)
    assert len(directory) >= 14

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
                        "text": "AAPL revenue",
                        "sequence_index": 1,
                        "required_capabilities": ["retrieval.run"],
                        "risk": "read",
                        "status": "ready",
                        "metadata": {
                            "capability_args": {
                                "retrieval.run": {
                                    "query": "AAPL revenue",
                                    "metadata": {"research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID},
                                }
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

    result = AgentRuntime(journal=journal, processor_fabric=fabric).run(
        "research AAPL revenue",
        mode="auto",
        semantic_mode="model",
        execution_metadata={
            "retrieval": {
                "metadata": {
                    "research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID,
                    "research_depth": "balanced",
                }
            }
        },
    )

    context = journal.records(task_id=result.task_id, kind="context")[0].data["state"]
    injected = context["research_source_directory"]
    assert injected
    assert {entry["source_family"] for entry in injected} >= {"regulatory_filing", "company_ir", "exchange_filing"}
    assert any("SEC" in entry["title"] for entry in injected)


def test_phase94_finance_profile_capability_routes_to_retrieval_without_workspace_collapse():
    journal = JournalStore.in_memory()
    fabric = fake_fabric(
        {
            "semantic.intake": {
                "primary_intent": "finance_fundamentals",
                "suggested_mode": "retrieval_answer",
                "compound": False,
                "requires_clarification": False,
                "intents": [
                    {
                        "kind": "finance_fundamentals",
                        "text": "Research AAPL revenue fundamentals",
                        "sequence_index": 1,
                        "required_capabilities": ["finance.fundamentals_research"],
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
        "Research AAPL revenue fundamentals",
        mode="auto",
        semantic_mode="model",
    )

    assert result.mode == "retrieval_answer"
    graph = journal.records(task_id=result.task_id, kind="semantic_task_graph")[0].data
    assert graph["validation"]["status"] == "ready"
    plan = journal.records(task_id=result.task_id, kind="semantic_task_plan")[0].data
    assert plan["selected_mode"] == "retrieval_answer"
    assert plan["steps"][0]["tool_name"] == "retrieval.run"
    context = journal.records(task_id=result.task_id, kind="context")[0].data["state"]
    assert context["research_source_directory"]
    action = journal.records(task_id=result.task_id, kind="action")[0].data
    assert action["name"] == "retrieval.run"
    assert action["payload"]["metadata"]["research_profile"] == FINANCE_FUNDAMENTALS_PROFILE_ID


def test_phase94_finance_profile_can_drive_multiple_retrieval_loop_actions():
    journal = JournalStore.in_memory()
    queries = [
        "AAPL 2024 10-K revenue",
        "AAPL 2024 investor relations margin",
    ]
    fabric = fake_fabric(
        {
            "semantic.intake": {
                "primary_intent": "finance_fundamentals",
                "suggested_mode": "retrieval_answer",
                "compound": True,
                "requires_clarification": False,
                "intents": [
                    {
                        "kind": "finance_fundamentals",
                        "text": queries[0],
                        "sequence_index": 1,
                        "required_capabilities": ["finance.fundamentals_research"],
                        "risk": "read",
                        "status": "ready",
                        "metadata": {},
                    },
                    {
                        "kind": "finance_fundamentals",
                        "text": queries[1],
                        "sequence_index": 2,
                        "required_capabilities": ["finance.fundamentals_research"],
                        "risk": "read",
                        "status": "ready",
                        "metadata": {},
                    },
                ],
                "blocked_capabilities": [],
                "warnings": [],
                "response_hint": None,
                "clarification_question": None,
            }
        },
        journal=journal,
    )
    operator = RetrievalOperator(
        search_provider=FakeSearchProvider(
            {
                queries[0]: [
                    _source(
                        "sec-aapl-10k",
                        "https://www.sec.gov/Archives/edgar/data/320193/aapl-20240928.htm",
                        "Apple 2024 Form 10-K",
                        "Official SEC filing revenue evidence.",
                    )
                ],
                queries[1]: [
                    _source(
                        "apple-ir",
                        "https://www.apple.com/investor-relations/earnings-releases/",
                        "Apple investor relations earnings release",
                        "Issuer-hosted margin and earnings release evidence.",
                    )
                ],
            }
        ),
        fetch_provider=FakeFetchProvider(
            {
                "https://www.sec.gov/Archives/edgar/data/320193/aapl-20240928.htm": (
                    "Apple 2024 Form 10-K revenue was $391.0 billion in the official SEC filing."
                ),
                "https://www.apple.com/investor-relations/earnings-releases/": (
                    "Apple investor relations earnings release reported gross margin of 46.2%."
                ),
            }
        ),
    )

    result = AgentRuntime(
        journal=journal,
        artifact_store=ArtifactStore.in_memory(),
        processor_fabric=fabric,
        retrieval_operator=operator,
    ).run(
        "Research AAPL revenue and margin from primary sources",
        mode="auto",
        semantic_mode="model",
    )

    assert result.status == "completed"
    actions = journal.records(task_id=result.task_id, kind="action")
    assert [record.data["name"] for record in actions] == ["retrieval.run", "retrieval.run"]
    assert all(
        record.data["payload"]["metadata"]["research_profile"] == FINANCE_FUNDAMENTALS_PROFILE_ID
        for record in actions
    )
    decisions = journal.records(task_id=result.task_id, kind="termination_decision")
    assert [record.data["decision"] for record in decisions] == ["continue", "final_answer"]
    reports = journal.records(task_id=result.task_id, kind="retrieval_report")
    assert [record.data["status"] for record in reports] == ["sufficient", "sufficient"]
    assert len(result.final_answer["citation_refs"]) == 2


def test_phase94_single_semantic_research_intent_expands_multiple_retrieval_payloads():
    journal = JournalStore.in_memory()
    payloads = [
        {
            "query": "AAPL 2024 official filing revenue",
            "metadata": {
                "research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID,
                "source_authority_requirement": "primary",
                "research_task_kind": "fundamentals",
            },
        },
        {
            "query": "AAPL 2024 investor relations margin",
            "metadata": {
                "research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID,
                "source_authority_requirement": "primary",
                "research_task_kind": "fundamentals",
            },
        },
        {
            "query": "AAPL 2024 competitive landscape services",
            "metadata": {
                "research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID,
                "source_authority_requirement": "secondary_or_better",
                "research_task_kind": "competitive_landscape",
            },
        },
    ]
    fabric = fake_fabric(
        {
            "semantic.intake": {
                "primary_intent": "finance_fundamentals_research_plan",
                "suggested_mode": "retrieval_answer",
                "compound": True,
                "requires_clarification": False,
                "intents": [
                    {
                        "kind": "finance_fundamentals_research_plan",
                        "text": "research Apple revenue, margin, and competitive services context",
                        "sequence_index": 1,
                        "required_capabilities": ["finance.fundamentals_research", "finance.competitive_landscape"],
                        "risk": "read",
                        "status": "ready",
                        "metadata": {
                            "domain": "finance",
                            "activity": "research",
                            "capability_args": {"retrieval.run": payloads},
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
    urls = {
        payloads[0]["query"]: "https://www.sec.gov/Archives/edgar/data/320193/aapl-20240928.htm",
        payloads[1]["query"]: "https://www.apple.com/investor-relations/earnings-releases/",
        payloads[2]["query"]: "https://www.reuters.com/technology/apple-services-market-context/",
    }
    operator = RetrievalOperator(
        search_provider=FakeSearchProvider(
            {
                query: [
                    _source(
                        f"src-{index}",
                        url,
                        f"Apple research source {index}",
                        f"Evidence for {query}.",
                    )
                ]
                for index, (query, url) in enumerate(urls.items(), start=1)
            }
        ),
        fetch_provider=FakeFetchProvider(
            {
                urls[payloads[0]["query"]]: "Apple 2024 Form 10-K official SEC filing revenue was $391.0 billion.",
                urls[payloads[1]["query"]]: "Apple investor relations official gross margin was 46.2% in the earnings release.",
                urls[payloads[2]["query"]]: "Reuters reported Apple services competitive landscape context.",
            }
        ),
    )

    result = AgentRuntime(
        journal=journal,
        artifact_store=ArtifactStore.in_memory(),
        processor_fabric=fabric,
        retrieval_operator=operator,
    ).run(
        "调研 Apple 的收入、利润率和服务业务竞争格局",
        mode="auto",
        semantic_mode="model",
    )

    assert result.status == "completed"
    plan = journal.records(task_id=result.task_id, kind="semantic_task_plan")[0].data
    assert len(plan["steps"][0]["metadata"]["capability_args"]["retrieval.run"]) == 3
    actions = journal.records(task_id=result.task_id, kind="action")
    assert [record.data["name"] for record in actions] == ["retrieval.run", "retrieval.run", "retrieval.run"]
    assert [record.data["payload"]["query"] for record in actions] == [payload["query"] for payload in payloads]
    assert actions[0].data["payload"]["metadata"]["source_authority_requirement"] == "primary"
    assert actions[2].data["payload"]["metadata"]["source_authority_requirement"] == "secondary_or_better"
    updates = journal.records(task_id=result.task_id, kind="agent_work_plan_update")
    assert [update.data["remaining_actions"] for update in updates] == [2, 1, 0]
    decisions = journal.records(task_id=result.task_id, kind="termination_decision")
    assert [record.data["decision"] for record in decisions] == ["continue", "continue", "final_answer"]
    assert len(result.final_answer["citation_refs"]) == 3


def test_phase94_single_retrieval_payload_runs_all_explicit_queries_without_max_query_hint():
    journal = JournalStore.in_memory()
    query = "AAPL 2024 revenue primary source"
    explicit_queries = [
        "AAPL 2024 revenue generic summary",
        "AAPL 2024 revenue annual report 10-K 10-Q filing",
        "AAPL 2024 revenue SEC EDGAR companyfacts",
    ]
    fabric = fake_fabric(
        {
            "semantic.intake": {
                "primary_intent": "finance_fundamentals_research",
                "suggested_mode": "retrieval_answer",
                "compound": False,
                "requires_clarification": False,
                "intents": [
                    {
                        "kind": "finance_fundamentals_research",
                        "text": query,
                        "sequence_index": 1,
                        "required_capabilities": ["finance.fundamentals_research"],
                        "risk": "read",
                        "status": "ready",
                        "metadata": {
                            "domain": "finance",
                            "activity": "research",
                            "capability_args": {
                                "retrieval.run": {
                                    "query": query,
                                    "queries": explicit_queries,
                                    "metadata": {
                                        "research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID,
                                        "research_depth": "light",
                                        "source_authority_requirement": "primary",
                                    },
                                }
                            },
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
    sec_url = "https://www.sec.gov/Archives/edgar/data/320193/aapl-20240928.htm"
    operator = RetrievalOperator(
        search_provider=FakeSearchProvider(
            {
                explicit_queries[0]: [
                    _source(
                        "src-generic",
                        "https://example.com/aapl-revenue-summary",
                        "Apple revenue summary",
                        "A generic summary that is not a primary source.",
                    )
                ],
                explicit_queries[1]: [
                    _source(
                        "src-sec-filing",
                        sec_url,
                        "Apple 2024 Form 10-K",
                        "Official SEC filing revenue evidence.",
                    )
                ],
                explicit_queries[2]: [],
            }
        ),
        fetch_provider=FakeFetchProvider(
            {
                "https://example.com/aapl-revenue-summary": "A third-party Apple revenue summary.",
                sec_url: "Apple 2024 Form 10-K official SEC filing revenue was $391.0 billion.",
            }
        ),
    )

    result = AgentRuntime(
        journal=journal,
        artifact_store=ArtifactStore.in_memory(),
        processor_fabric=fabric,
        retrieval_operator=operator,
    ).run(
        "调研 Apple 2024 收入，优先官方来源",
        mode="auto",
        semantic_mode="model",
    )

    assert result.status == "completed"
    actions = journal.records(task_id=result.task_id, kind="action")
    assert len(actions) == 1
    assert actions[0].data["payload"]["max_queries"] == 3
    assert actions[0].data["payload"]["metadata"]["research_depth"] == "light"
    plan = journal.records(task_id=result.task_id, kind="retrieval_query_plan")[0].data
    assert plan["queries"] == explicit_queries
    assert plan["diagnostics"]["query_count"] == 3
    attempts = journal.records(task_id=result.task_id, kind="retrieval_search_attempt")
    assert [record.data["query"] for record in attempts] == explicit_queries
    report = journal.records(task_id=result.task_id, kind="retrieval_report")[-1].data
    assert report["status"] == "sufficient"
    assert report["diagnostics"]["source_authority"]["primary_source_count"] == 1
    assert result.final_answer["citation_refs"]


def test_phase94_multi_payload_retrieval_requires_every_planned_subgoal_to_succeed():
    journal = JournalStore.in_memory()
    payloads = [
        {
            "query": "AAPL 2024 official filing revenue",
            "metadata": {"research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID},
        },
        {
            "query": "AAPL 2024 official filing margin missing",
            "metadata": {"research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID},
        },
        {
            "query": "AAPL 2024 investor relations services",
            "metadata": {"research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID},
        },
    ]
    fabric = fake_fabric(
        {
            "semantic.intake": {
                "primary_intent": "finance_fundamentals_research_plan",
                "suggested_mode": "retrieval_answer",
                "compound": True,
                "requires_clarification": False,
                "intents": [
                    {
                        "kind": "finance_fundamentals_research_plan",
                        "text": "research Apple revenue, margin, and services",
                        "sequence_index": 1,
                        "required_capabilities": ["finance.fundamentals_research"],
                        "risk": "read",
                        "status": "ready",
                        "metadata": {
                            "domain": "finance",
                            "activity": "research",
                            "capability_args": {"retrieval.run": payloads},
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
    operator = RetrievalOperator(
        search_provider=FakeSearchProvider(
            {
                payloads[0]["query"]: [
                    _source(
                        "src-revenue",
                        "https://www.sec.gov/Archives/edgar/data/320193/aapl-20240928.htm",
                        "Apple 2024 Form 10-K",
                        "Official revenue filing evidence.",
                    )
                ],
                payloads[1]["query"]: [],
                payloads[2]["query"]: [
                    _source(
                        "src-services",
                        "https://www.apple.com/investor-relations/earnings-releases/",
                        "Apple investor relations services context",
                        "Issuer-hosted services context.",
                    )
                ],
            }
        ),
        fetch_provider=FakeFetchProvider(
            {
                "https://www.sec.gov/Archives/edgar/data/320193/aapl-20240928.htm": (
                    "Apple 2024 Form 10-K official SEC filing revenue was $391.0 billion."
                ),
                "https://www.apple.com/investor-relations/earnings-releases/": (
                    "Apple investor relations official services context evidence."
                ),
            }
        ),
    )

    result = AgentRuntime(
        journal=journal,
        artifact_store=ArtifactStore.in_memory(),
        processor_fabric=fabric,
        retrieval_operator=operator,
    ).run(
        "调研 Apple 的收入、利润率和服务业务",
        mode="auto",
        semantic_mode="model",
    )

    assert result.status == "failed"
    assert result.final_answer is None
    assert result.failure_report["reason"] == "planned_retrieval_subgoals_incomplete"
    assert "retrieval_subgoal:goal-plan-1-2" in result.failure_report["missing_evidence"]
    reports = journal.records(task_id=result.task_id, kind="retrieval_report")
    assert [record.data["status"] for record in reports] == ["sufficient", "insufficient_evidence", "sufficient"]
    evidence_records = journal.records(task_id=result.task_id, kind="evidence_sufficiency")
    assert evidence_records[-2].data["sufficient"] is False
    coverage = evidence_records[-2].data["diagnostics"]["planned_retrieval_coverage"]
    assert coverage["incomplete_goal_ids"] == ["goal-plan-1-2"]
    assert coverage["latest_status_by_goal_id"]["goal-plan-1-2"] == "insufficient_evidence"
    assert not journal.records(task_id=result.task_id, kind="agent_final_answer")


def _source(source_id: str, uri: str, title: str, snippet: str) -> SearchSource:
    return SearchSource(
        source_id=source_id,
        uri=uri,
        title=title,
        snippet=snippet,
        provider="fake",
    )
