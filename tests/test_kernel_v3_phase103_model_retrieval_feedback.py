from kernel_v3.agent import AgentRuntime
from kernel_v3.context import ArtifactStore
from kernel_v3.journal import JournalStore
from kernel_v3.processors.testing import fake_fabric
from kernel_v3.research import FINANCE_FUNDAMENTALS_PROFILE_ID
from kernel_v3.retrieval import DirectUrlSearchProvider, FakeFetchProvider, RetrievalOperator


def test_phase103_model_retrieval_action_inherits_finance_profile_defaults_from_task_plan() -> None:
    query = "AAPL 2024 10-K revenue"
    sec_url = "https://www.sec.gov/Archives/edgar/data/320193/aapl-20240928.htm"
    journal = JournalStore.in_memory()
    fabric = fake_fabric(
        {
            "semantic.intake": _finance_semantic_intake(query),
            "planner.propose": {
                "action_id": "act-model-sec-retrieval",
                "kind": "tool",
                "name": "retrieval.run",
                "description": "retrieve official filing evidence",
                "payload": {"query": query, "source_url": sec_url},
                "score": 0.9,
                "reasons": ["official filing evidence required"],
                "side_effect_class": "read",
            },
        },
        journal=journal,
    )
    operator = RetrievalOperator(
        search_provider=DirectUrlSearchProvider(),
        fetch_provider=FakeFetchProvider(
            {
                sec_url: "Apple 2024 Form 10-K revenue evidence from the official SEC filing.",
            }
        ),
    )

    result = AgentRuntime(
        journal=journal,
        artifact_store=ArtifactStore.in_memory(),
        processor_fabric=fabric,
        retrieval_operator=operator,
    ).run(
        query,
        mode="auto",
        semantic_mode="model",
        planner_mode="model",
    )

    assert result.status == "completed"
    action_payload = journal.records(task_id=result.task_id, kind="action")[0].data["payload"]
    assert action_payload["metadata"]["research_profile"] == FINANCE_FUNDAMENTALS_PROFILE_ID
    assert action_payload["max_fetches"] >= 1
    report = journal.records(task_id=result.task_id, kind="retrieval_report")[-1].data
    assert report["status"] == "sufficient"


def test_phase103_source_authority_gap_feedback_drives_model_retrieval_replan() -> None:
    query = "AAPL 2024 10-K revenue"
    weak_url = "https://example.com/aapl-10k-summary"
    sec_url = "https://www.sec.gov/Archives/edgar/data/320193/aapl-20240928.htm"
    journal = JournalStore.in_memory()
    fabric = fake_fabric(
        {
            "semantic.intake": _finance_semantic_intake(query),
            "planner.propose": [
                {
                    "action_id": "act-model-weak-retrieval",
                    "kind": "tool",
                    "name": "retrieval.run",
                    "description": "try a third-party summary first",
                    "payload": {"query": query, "source_url": weak_url},
                    "score": 0.85,
                    "reasons": ["needs current evidence"],
                    "side_effect_class": "read",
                },
                {
                    "action_id": "act-model-sec-retrieval",
                    "kind": "tool",
                    "name": "retrieval.run",
                    "description": "retry with official SEC filing",
                    "payload": {"query": query, "source_url": sec_url},
                    "score": 0.95,
                    "reasons": ["feedback requested primary source authority"],
                    "side_effect_class": "read",
                },
            ],
        },
        journal=journal,
    )
    operator = RetrievalOperator(
        search_provider=DirectUrlSearchProvider(),
        fetch_provider=FakeFetchProvider(
            {
                weak_url: "A third-party web page repeats Apple revenue from a filing.",
                sec_url: "Apple 2024 Form 10-K revenue evidence from the official SEC filing.",
            }
        ),
    )

    result = AgentRuntime(
        journal=journal,
        artifact_store=ArtifactStore.in_memory(),
        processor_fabric=fabric,
        retrieval_operator=operator,
    ).run(
        query,
        mode="auto",
        semantic_mode="model",
        planner_mode="model",
    )

    assert result.status == "completed"
    actions = journal.records(task_id=result.task_id, kind="action")
    assert [record.data["payload"]["source_url"] for record in actions] == [weak_url, sec_url]
    decisions = journal.records(task_id=result.task_id, kind="termination_decision")
    assert decisions[0].data["decision"] == "continue"
    assert "primary_source" in decisions[0].data["diagnostics"]["evidence_missing"]
    updates = journal.records(task_id=result.task_id, kind="agent_work_plan_update")
    assert "source_authority:primary" in updates[1].data["feedback_missing_evidence"]
    assert "primary_source" in updates[1].data["feedback_missing_evidence"]
    replan = updates[1].data["replan_hints"]
    assert replan["status"] == "needs_replan"
    assert replan["suggested_next_action"] == "propose_materially_new_retrieval_run"
    assert replan["avoid_repeating"]["recent_payload_hashes"]
    retrieval_replan = replan["retrieval"]
    assert retrieval_replan["needs_replan"] is True
    assert retrieval_replan["latest_report_status"] == "insufficient_evidence"
    assert "primary_source" in retrieval_replan["missing"]
    assert "source_authority:primary" in retrieval_replan["missing"]
    assert "structured" in retrieval_replan["suggested_search_strategies"]
    assert "official filing" in " ".join(retrieval_replan["suggested_query_hints"])
    assert retrieval_replan["suggested_source_targets"]
    top_target = retrieval_replan["suggested_source_targets"][0]
    assert top_target["authority_level"] == "primary"
    assert top_target["source_family"] in {
        "regulatory_filing",
        "structured_regulatory_data",
        "company_ir",
        "exchange_filing",
    }
    assert top_target["base_url"].startswith("https://")
    assert top_target["suggested_payload_metadata"]["search_strategy"] == "structured"
    assert top_target["suggested_payload_metadata"]["research_profile"] == FINANCE_FUNDAMENTALS_PROFILE_ID
    assert "primary source authority requirement is satisfied" in retrieval_replan["do_not_finalize_until"]
    contexts = journal.records(task_id=result.task_id, kind="context")
    second_context_replan = contexts[1].data["state"]["agent_replan_hints"]
    assert second_context_replan["status"] == "needs_replan"
    assert second_context_replan["retrieval"]["source_authority_requirement"] == "primary"
    assert second_context_replan["retrieval"]["suggested_source_targets"][0]["source_id"] == top_target["source_id"]
    reports = journal.records(task_id=result.task_id, kind="retrieval_report")
    assert reports[0].data["status"] == "insufficient_evidence"
    assert reports[-1].data["status"] == "sufficient"
    assert result.final_answer["citation_refs"]


def test_phase103_planned_subgoal_coverage_feedback_drives_model_retry() -> None:
    query = "AAPL 2024 revenue margin services"
    revenue_url = "https://www.sec.gov/Archives/edgar/data/320193/aapl-20240928.htm"
    weak_margin_url = "https://example.com/aapl-margin-summary"
    services_url = "https://www.apple.com/investor-relations/earnings-releases/"
    margin_retry_url = "https://www.sec.gov/Archives/edgar/data/320193/aapl-margin-note.htm"
    journal = JournalStore.in_memory()
    semantic = _finance_semantic_intake(query)
    semantic["intents"][0]["metadata"] = {
        "capability_args": {
            "retrieval.run": [
                {"goal_id": "goal-plan-1-1", "query": "AAPL 2024 revenue official filing"},
                {"goal_id": "goal-plan-1-2", "query": "AAPL 2024 margin official source"},
                {"goal_id": "goal-plan-1-3", "query": "AAPL 2024 services investor relations"},
            ]
        }
    }
    fabric = fake_fabric(
        {
            "semantic.intake": semantic,
            "planner.propose": [
                {
                    "action_id": "act-model-revenue",
                    "kind": "tool",
                    "name": "retrieval.run",
                    "description": "retrieve official revenue filing evidence",
                    "payload": {
                        "goal_id": "goal-plan-1-1",
                        "query": "AAPL 2024 revenue official filing",
                        "source_url": revenue_url,
                    },
                    "score": 0.92,
                    "reasons": ["planned revenue subgoal"],
                    "side_effect_class": "read",
                },
                {
                    "action_id": "act-model-margin-weak",
                    "kind": "tool",
                    "name": "retrieval.run",
                    "description": "try margin evidence from a summary",
                    "payload": {
                        "goal_id": "goal-plan-1-2",
                        "query": "AAPL 2024 margin official source",
                        "source_url": weak_margin_url,
                    },
                    "score": 0.82,
                    "reasons": ["planned margin subgoal"],
                    "side_effect_class": "read",
                },
                {
                    "action_id": "act-model-services",
                    "kind": "tool",
                    "name": "retrieval.run",
                    "description": "retrieve official services context",
                    "payload": {
                        "goal_id": "goal-plan-1-3",
                        "query": "AAPL 2024 services investor relations",
                        "source_url": services_url,
                    },
                    "score": 0.9,
                    "reasons": ["planned services subgoal"],
                    "side_effect_class": "read",
                },
                {
                    "action_id": "act-model-margin-retry",
                    "kind": "tool",
                    "name": "retrieval.run",
                    "description": "retry the incomplete margin subgoal with a primary source",
                    "payload": {
                        "goal_id": "goal-plan-1-2",
                        "query": "AAPL 2024 margin SEC filing",
                        "source_url": margin_retry_url,
                    },
                    "score": 0.96,
                    "reasons": ["replan_hints requested retry for goal-plan-1-2"],
                    "side_effect_class": "read",
                },
            ],
        },
        journal=journal,
    )
    operator = RetrievalOperator(
        search_provider=DirectUrlSearchProvider(),
        fetch_provider=FakeFetchProvider(
            {
                revenue_url: "Apple 2024 Form 10-K official SEC filing revenue evidence.",
                weak_margin_url: "A third-party page discusses Apple margin without primary authority.",
                services_url: "Apple investor relations official services and results context.",
                margin_retry_url: "Apple 2024 SEC filing official gross margin evidence.",
            }
        ),
    )

    result = AgentRuntime(
        journal=journal,
        artifact_store=ArtifactStore.in_memory(),
        processor_fabric=fabric,
        retrieval_operator=operator,
    ).run(
        query,
        mode="auto",
        semantic_mode="model",
        planner_mode="model",
    )

    assert result.status == "completed"
    contexts = journal.records(task_id=result.task_id, kind="context")
    initial_plan_state = contexts[0].data["state"]["agent_retrieval_plan_state"]
    assert initial_plan_state["status"] == "needs_retrieval"
    assert initial_plan_state["planned_goal_ids"] == ["goal-plan-1-1", "goal-plan-1-2", "goal-plan-1-3"]
    assert initial_plan_state["pending_goal_ids"] == ["goal-plan-1-1", "goal-plan-1-2", "goal-plan-1-3"]
    assert initial_plan_state["next_recommended_goal_id"] == "goal-plan-1-1"
    assert [subgoal["goal_id"] for subgoal in initial_plan_state["planned_subgoals"]] == [
        "goal-plan-1-1",
        "goal-plan-1-2",
        "goal-plan-1-3",
    ]
    actions = journal.records(task_id=result.task_id, kind="action")
    assert [record.data["payload"]["goal_id"] for record in actions] == [
        "goal-plan-1-1",
        "goal-plan-1-2",
        "goal-plan-1-3",
        "goal-plan-1-2",
    ]
    reports = journal.records(task_id=result.task_id, kind="retrieval_report")
    assert [record.data["status"] for record in reports] == [
        "sufficient",
        "insufficient_evidence",
        "sufficient",
        "sufficient",
    ]
    updates = journal.records(task_id=result.task_id, kind="agent_work_plan_update")
    retry_hints = updates[3].data["replan_hints"]
    retry_plan_state = updates[3].data["retrieval_plan_state"]
    assert retry_plan_state["status"] == "needs_replan"
    assert retry_plan_state["next_recommended_goal_id"] == "goal-plan-1-2"
    assert retry_plan_state["incomplete_goal_ids"] == ["goal-plan-1-2"]
    assert retry_hints["status"] == "needs_replan"
    assert retry_hints["suggested_next_action"] == "retry_incomplete_planned_retrieval_subgoals"
    assert retry_hints["retrieval"]["latest_report_status"] == "sufficient"
    assert retry_hints["retrieval"]["incomplete_planned_goal_ids"] == ["goal-plan-1-2"]
    assert "retrieval_subgoal:goal-plan-1-2 sufficient" in retry_hints["retrieval"]["do_not_finalize_until"]
    retry_context_plan_state = contexts[3].data["state"]["agent_retrieval_plan_state"]
    assert retry_context_plan_state["status"] == "needs_replan"
    assert retry_context_plan_state["next_recommended_goal_id"] == "goal-plan-1-2"
    assert contexts[3].data["state"]["agent_replan_hints"]["retrieval"]["planned_retrieval_coverage"][
        "incomplete_goal_ids"
    ] == ["goal-plan-1-2"]
    final_evidence = journal.records(task_id=result.task_id, kind="evidence_sufficiency")[-1].data
    assert final_evidence["diagnostics"]["planned_retrieval_coverage"]["sufficient"] is True
    assert len(result.final_answer["citation_refs"]) == 4


def _finance_semantic_intake(query: str) -> dict:
    return {
        "primary_intent": "finance_fundamentals",
        "suggested_mode": "retrieval_answer",
        "compound": False,
        "requires_clarification": False,
        "intents": [
            {
                "kind": "finance_fundamentals",
                "text": query,
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
