from pathlib import Path

from kernel_v3.agent import AgentRuntime
from kernel_v3.capabilities import semantic_capability_catalog
from kernel_v3.journal import JournalStore
from kernel_v3.processors.testing import fake_fabric
from kernel_v3.research import FINANCE_FUNDAMENTALS_PROFILE_ID, finance_fundamentals_source_directory


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
    assert {"conversation", "workspace", "retrieval", "finance", "memory", "resident", "transport", "system"}.issubset(families)
    capability_ids = {item["capability_id"] for item in catalog["capabilities"]}
    assert {
        "workspace.file.write",
        "web.search",
        "web.crawl",
        "finance.fundamentals_research",
        "durable_memory.propose",
        "resident.scheduler",
        "transport.wechat",
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
    assert "resident" in families
    assert "transport" in families
    assert "system" in families
    assert "workspace_write" in catalog["modes"]
    assert "system_answer" in catalog["modes"]
    assert catalog["executable_tools_by_recipe"]["system_answer"] == ["system.time"]


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


def test_phase94_finance_source_directory_is_structured_and_context_injected(tmp_path):
    directory = finance_fundamentals_source_directory()
    source_ids = {entry.source_id for entry in directory}
    assert {
        "finance-sec-edgar-filings",
        "finance-sec-companyfacts",
        "finance-company-investor-relations",
        "finance-us-official-statistics",
        "finance-china-exchange-disclosures",
        "finance-hkex-disclosures",
        "finance-market-data-secondary",
    }.issubset(source_ids)
    assert all(entry.allowed_hosts for entry in directory)
    assert all(entry.query_hints for entry in directory)

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
