from pathlib import Path

from kernel_v3.agent import AgentRuntime
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
                    "Apple 2024 Form 10-K revenue was reported in the official SEC filing."
                ),
                "https://www.apple.com/investor-relations/earnings-releases/": (
                    "Apple investor relations earnings release discussed gross margin and results."
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


def _source(source_id: str, uri: str, title: str, snippet: str) -> SearchSource:
    return SearchSource(
        source_id=source_id,
        uri=uri,
        title=title,
        snippet=snippet,
        provider="fake",
    )
