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
    reports = journal.records(task_id=result.task_id, kind="retrieval_report")
    assert reports[0].data["status"] == "insufficient_evidence"
    assert reports[-1].data["status"] == "sufficient"
    assert result.final_answer["citation_refs"]


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
