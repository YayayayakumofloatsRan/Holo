import json

from kernel_v3.agent.runtime import AgentRuntime, _agent_replan_hints, _bind_model_action_to_recipe, task_recipe
from kernel_v3.context.compiler import ContextPackCompiler
from kernel_v3.contracts import CandidateAction, ContextBundle
from kernel_v3.journal import JournalStore
from kernel_v3.memory import MEMORY_RECALL_TOOL_NAME, MemoryStore, register_memory_tools
from kernel_v3.processors.contracts import JsonSchema
from kernel_v3.processors.fabric import ProcessorFabric
from kernel_v3.processors.routing import ProcessorRouter
from kernel_v3.processors.testing import fake_fabric
from kernel_v3.resident.queue import ResidentQueue
from kernel_v3.retrieval.contracts import FetchedDocument, SearchGoal
from kernel_v3.retrieval.extract import extract_spans, readable_document_text
from kernel_v3.retrieval.strategy import materially_different_query, supervise_retrieval_payload


def test_phase112_memory_package_imports_do_not_cycle():
    assert MemoryStore is not None
    assert ContextPackCompiler is not None
    assert MEMORY_RECALL_TOOL_NAME == "memory.recall"
    assert callable(register_memory_tools)


def test_phase112_strategy_supervisor_rewrites_repeated_retrieval_payload():
    decision = supervise_retrieval_payload(
        {
            "query": "Citadel Security company size employees revenue",
            "metadata": {"search_strategy": "aggregate"},
        },
        replan_hints={
            "needs_replan": True,
            "attempted_queries": ["Citadel Security company size employees revenue"],
            "attempted_search_strategies": ["aggregate"],
            "suggested_search_strategies": ["structured", "fresh_live"],
            "suggested_query_hints": [
                "Citadel Security private security contractor operations",
                "Citadel Security licensed security company headquarters staff",
            ],
            "suggested_source_targets": [
                {
                    "source_id": "gov-corporate-registry",
                    "title": "corporate registry",
                    "source_family": "company_registry",
                    "query_hints": ["company registration officers filings"],
                }
            ],
            "missing": ["query_facet:operations", "candidate_source_rejected"],
        },
        root_goal="Research Citadel Security",
    )

    payload = decision.payload
    assert payload["query"] != "Citadel Security company size employees revenue"
    assert materially_different_query(payload["query"], ["Citadel Security company size employees revenue"])
    assert payload["metadata"]["search_strategy"] == "structured"
    assert payload["metadata"]["preferred_source_families"] == ["company_registry"]
    assert payload["metadata"]["strategy_supervision"]["status"] == "enforced"
    assert payload["max_queries"] >= 8
    assert payload["queries"][0] == payload["query"]


def test_phase112_model_retrieval_action_binding_enforces_replan_constraints():
    recipe = task_recipe(
        "retrieval",
        metadata={"execution_metadata": {"retrieval": {"allow_network": True, "max_network_fetches": 100}}},
    )
    context = ContextBundle(
        context_id="ctx-replan",
        thread_key="thread",
        event_ids=[],
        memory_refs=[],
        token_budget=4096,
        state={
            "run_id": "run-1",
            "agent_replan_hints": {
                "retrieval": {
                    "needs_replan": True,
                    "attempted_queries": ["hyperbolic dynamics definition"],
                    "attempted_search_strategies": ["aggregate"],
                    "suggested_search_strategies": ["structured", "fresh_live"],
                    "suggested_query_hints": [
                        "hyperbolic dynamics recent arxiv papers survey open problems",
                        "hyperbolic dynamics latest research literature review",
                    ],
                    "missing": ["query_facet:scholarly_work", "query_facet:frontier_or_recent"],
                }
            },
        },
    )
    action = CandidateAction(
        action_id="act-repeated",
        kind="tool",
        name="retrieval.run",
        description="repeat bad query",
        payload={"query": "hyperbolic dynamics definition", "metadata": {"search_strategy": "aggregate"}},
        reasons=["try scholarly sources"],
        score=0.9,
        side_effect_class="network",
    )

    bound = _bind_model_action_to_recipe(action, goal="Search hyperbolic dynamics frontier research", recipe=recipe, context=context)

    assert bound.payload["query"] == "hyperbolic dynamics recent arxiv papers survey open problems"
    assert bound.payload["metadata"]["search_strategy"] == "structured"
    assert "host_strategy_supervision_rewrote_retrieval_payload" in bound.reasons
    diagnostics = bound.payload["metadata"]["strategy_supervision_diagnostics"]
    assert diagnostics["rewritten"] is True
    assert diagnostics["previous_query"] == "hyperbolic dynamics definition"


def test_phase112_mission_directive_becomes_hard_retrieval_replan_hint():
    recipe = task_recipe(
        "retrieval",
        metadata={
            "execution_metadata": {
                "retrieval": {"allow_network": True, "max_network_fetches": 100},
                "mission_context": {
                    "mission_state": {"root_goal": "Research a difficult entity", "directive": {}},
                    "directive": {
                        "strategy": "fresh_live",
                        "next_subgoal": "use a different authoritative source family",
                        "missing_requirements": ["entity_disambiguation", "operations_evidence"],
                        "avoid_repeating": ["Citadel Security company size employees revenue"],
                    },
                },
            }
        },
    )
    hints = _agent_replan_hints(JournalStore.in_memory(), task_id="task-1", run_id="run-2", recipe=recipe)

    retrieval = hints["retrieval"]
    assert retrieval["needs_replan"] is True
    assert "Citadel Security company size employees revenue" in retrieval["attempted_queries"]
    assert retrieval["suggested_search_strategies"][0] == "fresh_live"
    assert "operations_evidence" in retrieval["missing"]


def test_phase112_sec_companyfacts_extraction_marks_annual_and_recent_facts():
    body = json.dumps(
        {
            "entityName": "ORACLE CORP",
            "cik": "0001341439",
            "facts": {
                "us-gaap": {
                    "Revenues": {
                        "label": "Revenues",
                        "units": {
                            "USD": [
                                {"val": 39000000000, "fy": 2018, "fp": "FY", "form": "10-K", "filed": "2018-08-01", "end": "2018-05-31", "start": "2017-06-01"},
                                {"val": 15000000000, "fy": 2026, "fp": "Q1", "form": "10-Q", "filed": "2025-09-10", "end": "2025-08-31", "start": "2025-06-01"},
                                {"val": 57000000000, "fy": 2025, "fp": "FY", "form": "10-K", "filed": "2025-06-20", "end": "2025-05-31", "start": "2024-06-01"},
                            ]
                        },
                    }
                }
            },
        },
        ensure_ascii=False,
    )
    document = FetchedDocument(
        document_id="doc-sec",
        goal_id="goal-sec",
        source_id="src-sec",
        uri="https://data.sec.gov/api/xbrl/companyfacts/CIK0001341439.json",
        title="SEC companyfacts",
        artifact_id="artifact-sec",
        payload_hash="hash",
        preview="SEC facts",
        size_bytes=len(body),
        metadata={"mime_type": "application/json"},
    )
    text, mode = readable_document_text(body, document=document)
    annual_index = text.index("period=annual")
    quarterly_index = text.index("period=quarterly")
    assert mode == "sec_companyfacts_readable_text"
    assert annual_index < quarterly_index
    assert "fy=2025" in text
    spans = extract_spans(
        goal=SearchGoal(goal_id="goal-sec", query="annual revenue financial statement", max_spans_per_document=2),
        document=document,
        body=body,
    )
    assert spans
    assert "period=annual" in spans[0].text
    assert "fy=2025" in spans[0].text


def test_phase112_resident_cancel_prevents_claim(tmp_path):
    queue = ResidentQueue(tmp_path / "resident.sqlite")
    message = queue.enqueue(thread_id="thread", text="background research")
    canceled = queue.cancel(message.message_id, reason="user_interrupt")

    assert canceled is not None
    assert canceled.status == "canceled"
    assert canceled.metadata["cancel_reason"] == "user_interrupt"
    assert queue.acquire_lease(worker_id="worker") is not None
    assert queue.claim_next(worker_id="worker") is None


def test_phase112_external_model_blocks_private_context_without_authorization():
    journal = JournalStore.in_memory()
    provider = _ExternalProvider()
    fabric = ProcessorFabric(
        providers={"deepseek": provider},
        router=ProcessorRouter(default_provider="deepseek", default_model="deepseek-v4-flash"),
        journal=journal,
    )

    outcome = fabric.run_json(
        task_type="planner.propose",
        task_id="task-private",
        run_id="run-private",
        context_id="ctx-private",
        prompt='{"durable_memory":{"items":[{"privacy_class":"sensitive","summary":"private note"}]}}',
        schema=JsonSchema(name="planner.propose", required={"ok": "bool"}),
    )

    assert outcome.result.status == "failed"
    assert outcome.result.error == "private_context_external_model_blocked:sensitive_context_marker"
    assert provider.calls == 0
    result_record = journal.records(task_id="task-private", kind="processor_result")[-1]
    assert result_record.data["output"]["redaction"]["prompt"] == "not_sent_to_provider"


def test_phase112_external_model_can_be_explicitly_authorized_for_private_context():
    provider = _ExternalProvider()
    fabric = ProcessorFabric(
        providers={"deepseek": provider},
        router=ProcessorRouter(default_provider="deepseek", default_model="deepseek-v4-flash"),
    )

    outcome = fabric.run_json(
        task_type="planner.propose",
        run_id="run-private",
        context_id="ctx-private",
        prompt='{"private_context":true}',
        schema=JsonSchema(name="planner.propose", required={"ok": "bool"}),
        parameters={"allow_private_context_to_external_model": True},
    )

    assert outcome.result.status == "ok"
    assert outcome.parsed == {"ok": True}
    assert provider.calls == 1


def test_phase112_spurious_system_answer_without_system_tool_downgrades_to_semantic_answer():
    journal = JournalStore.in_memory()
    fabric = fake_fabric(
        {
            "semantic.intake": {
                "primary_intent": "system_capability_check",
                "suggested_mode": "system_answer",
                "compound": False,
                "requires_clarification": False,
                "intents": [
                    {
                        "kind": "system_capability_check",
                        "text": "can the live model call return a visible answer",
                        "sequence_index": 1,
                        "required_capabilities": ["system.time"],
                        "risk": "none",
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
        "请确认模型调用是否能返回用户可见答案",
        mode="auto",
        semantic_mode="model",
    )

    assert result.status == "completed"
    assert result.mode == "semantic_answer"
    assert not journal.records(task_id=result.task_id, kind="system_time")
    assert all(record.data.get("name") != "system.time" for record in journal.records(task_id=result.task_id, kind="action"))


class _ExternalProvider:
    name = "deepseek"
    model = "deepseek-v4-flash"

    def __init__(self) -> None:
        self.calls = 0

    def run(self, request):
        from kernel_v3.contracts import ProcessorResult

        self.calls += 1
        return ProcessorResult(
            result_id=f"result-{request.request_id}",
            request_id=request.request_id,
            status="ok",
            output={"text": '{"ok": true}', "provider": self.name, "model": self.model},
            usage={},
            error=None,
        )
