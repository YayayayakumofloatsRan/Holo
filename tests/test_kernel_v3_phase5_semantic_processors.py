import json
from pathlib import Path

from kernel_v3.context import ContextCompiler
from kernel_v3.contracts import CandidateAction
from kernel_v3.journal import JournalStore
from kernel_v3.loop import LoopControllerV3
from kernel_v3.policy import PolicyGate
from kernel_v3.processors import (
    PLANNER_SCHEMA,
    DeepSeekProvider,
    FakeJsonProvider,
    FakeMalformedJsonProvider,
    ModelEvaluator,
    ModelPlanner,
    ProcessorFabric,
    ProcessorRoute,
    ProcessorRouter,
    Synthesizer,
)
from kernel_v3.processors.testing import fake_fabric, timeout_fabric
from kernel_v3.retrieval.contracts import CitationItem, EvidenceItem, RetrievalReport
from kernel_v3.testing.fakes import FakeEvaluator, FakePlanner
from kernel_v3.tools import ToolRegistry
from kernel_v3.trace import TraceRenderer


def test_phase5_fake_provider_produces_valid_candidate_action_and_journals_processor_call():
    journal = JournalStore.in_memory()
    registry = ToolRegistry()
    action_payload = {
        "action_id": "act-retrieve",
        "kind": "tool",
        "name": "retrieval.run",
        "description": "run retrieval",
        "payload": {"query": "Kernel v3"},
        "score": 0.9,
        "reasons": ["need evidence"],
        "side_effect_class": "read",
    }
    planner = ModelPlanner(
        fabric=fake_fabric({"planner.propose": action_payload}, journal=journal),
        allowed_tool_names={"retrieval.run"},
    )
    context = _context()

    action = planner.propose(context)

    assert action == CandidateAction(**action_payload)
    assert [record.kind for record in journal.records(task_id="task-1")] == [
        "processor_request",
        "processor_result",
    ]
    result = journal.records(task_id="task-1", kind="processor_result")[0]
    assert result.data["status"] == "ok"
    assert result.data["task_type"] == "planner.propose"
    assert result.data["usage"]["total_tokens"] > 0
    assert registry.executed_actions == []


def test_phase5_malformed_planner_json_is_rejected_and_journaled_without_crashing_loop():
    journal = JournalStore.in_memory()
    fabric = ProcessorFabric(
        providers={"fake_malformed_json": FakeMalformedJsonProvider("not-json")},
        router=ProcessorRouter(default_provider="fake_malformed_json", default_model="fake-malformed-json"),
        journal=journal,
    )
    planner = ModelPlanner(fabric=fabric)
    loop = LoopControllerV3(
        journal=journal,
        context_compiler=ContextCompiler(),
        planner=planner,
        policy_gate=PolicyGate(permission="read_write"),
        tool_registry=ToolRegistry.with_builtin_respond(),
        evaluator=FakeEvaluator.needs_user_input("planner failed"),
    )

    result = loop.run("plan badly")

    assert result.status == "needs_user_input"
    action = journal.records(task_id=result.task_id, kind="action")[0]
    processor_result = journal.records(task_id=result.task_id, kind="processor_result")[0]
    assert action.data["kind"] == "ask_user"
    assert action.data["reasons"] == ["processor_failed"]
    assert processor_result.data["status"] == "failed"
    assert processor_result.data["error"]


def test_phase5_json_repair_is_bounded_and_still_schema_validated():
    journal = JournalStore.in_memory()
    provider = FakeMalformedJsonProvider(
        """```json
{"action_id":"act-fixed","kind":"respond","name":null,"description":"ok","payload":{"text":"ok"},"score":1,"reasons":["repaired"],"side_effect_class":"none",}
```"""
    )
    fabric = ProcessorFabric(
        providers={"fake_malformed_json": provider},
        router=ProcessorRouter(default_provider="fake_malformed_json", default_model="fake-malformed-json"),
        journal=journal,
        max_repair_attempts=1,
    )

    outcome = fabric.run_json(
        task_type="planner.propose",
        task_id="task-1",
        run_id="run-1",
        context_id="ctx-1",
        prompt="repair",
        schema=PLANNER_SCHEMA,
    )

    assert outcome.result.status == "ok"
    assert outcome.repaired is True
    assert outcome.repair_attempts == 1


def test_phase5_model_planner_cannot_bypass_policy_gate_for_write_tool(tmp_path: Path):
    journal = JournalStore.in_memory()
    registry = ToolRegistry.with_permissioned_workspace(root=tmp_path)
    write_action = {
        "action_id": "act-write",
        "kind": "tool",
        "name": "workspace.write",
        "description": "write file",
        "payload": {"path": "notes.txt", "text": "model wrote this"},
        "score": 1.0,
        "reasons": ["model requested write"],
        "side_effect_class": "read",
    }
    planner = ModelPlanner(
        fabric=fake_fabric({"planner.propose": write_action}, journal=journal),
        allowed_tool_names={manifest.name for manifest in registry.manifests()},
    )
    loop = LoopControllerV3(
        journal=journal,
        context_compiler=ContextCompiler(),
        planner=planner,
        policy_gate=PolicyGate(permission="read_only"),
        tool_registry=registry,
        evaluator=FakeEvaluator.stop_on_block(),
    )

    result = loop.run("write a file")

    assert result.status == "blocked"
    assert registry.executed_actions == []
    assert not (tmp_path / "notes.txt").exists()
    policy = journal.records(task_id=result.task_id, kind="policy_decision")[0]
    assert policy.data["allowed"] is False
    assert policy.data["reason"] == "blocked_side_effect_in_read_only_mode"


def test_phase5_unregistered_model_tool_action_is_blocked_not_executed():
    journal = JournalStore.in_memory()
    unknown_action = {
        "action_id": "act-unknown",
        "kind": "tool",
        "name": "unknown.operator",
        "description": "unknown tool",
        "payload": {"value": 1},
        "score": 1.0,
        "reasons": ["model guessed a tool"],
        "side_effect_class": "read",
    }
    registry = ToolRegistry.with_builtin_respond()
    planner = ModelPlanner(fabric=fake_fabric({"planner.propose": unknown_action}, journal=journal))
    loop = LoopControllerV3(
        journal=journal,
        context_compiler=ContextCompiler(),
        planner=planner,
        policy_gate=PolicyGate(permission="read_write"),
        tool_registry=registry,
        evaluator=FakeEvaluator.stop_on_block(),
    )

    result = loop.run("unknown tool")

    assert result.status == "blocked"
    assert registry.executed_actions == []
    observation = journal.records(task_id=result.task_id, kind="observation")[0]
    assert observation.data["status"] == "blocked"
    assert observation.data["content"] == {"reason": "unregistered_tool", "tool": "unknown.operator"}


def test_phase5_model_evaluator_continue_drives_another_loop_step():
    journal = JournalStore.in_memory()
    actions = [_respond("act-1", "first"), _respond("act-2", "second")]
    evaluator = ModelEvaluator(
        fabric=fake_fabric(
            {
                "evaluator.assess": [
                    {"status": "continue", "answer": None, "stop_reason": None, "missing_evidence": ["need second"]},
                    {
                        "status": "final_answer_ready",
                        "answer": "second",
                        "stop_reason": "completed",
                        "missing_evidence": [],
                    },
                ]
            },
            journal=journal,
        )
    )
    loop = LoopControllerV3(
        journal=journal,
        context_compiler=ContextCompiler(),
        planner=FakePlanner(actions),
        policy_gate=PolicyGate(permission="read_write"),
        tool_registry=ToolRegistry.with_builtin_respond(),
        evaluator=evaluator,
    )

    result = loop.run("continue")

    assert result.status == "completed"
    assert [record.data["action_id"] for record in journal.records(task_id=result.task_id, kind="action")] == [
        "act-1",
        "act-2",
    ]
    assert [record.data["status"] for record in journal.records(task_id=result.task_id, kind="feedback")] == [
        "continue",
        "final_answer_ready",
    ]


def test_phase5_model_evaluator_final_answer_ready_stops_loop():
    journal = JournalStore.in_memory()
    evaluator = ModelEvaluator(
        fabric=fake_fabric(
            {
                "evaluator.assess": {
                    "status": "final_answer_ready",
                    "answer": "done",
                    "stop_reason": "completed",
                    "missing_evidence": [],
                }
            },
            journal=journal,
        )
    )
    loop = LoopControllerV3(
        journal=journal,
        context_compiler=ContextCompiler(),
        planner=FakePlanner([_respond("act-1", "done")]),
        policy_gate=PolicyGate(permission="read_write"),
        tool_registry=ToolRegistry.with_builtin_respond(),
        evaluator=evaluator,
    )

    result = loop.run("finish")

    assert result.status == "completed"
    assert result.answer == "done"
    assert len(journal.records(task_id=result.task_id, kind="action")) == 1


def test_phase5_synthesizer_only_uses_known_citation_refs_and_fails_unknown_refs():
    report, evidence, citation = _retrieval_contracts()
    ok = Synthesizer(
        fabric=fake_fabric(
            {
                "synthesizer.answer": {
                    "answer": "Kernel v3 cites evidence.",
                    "citation_refs": ["cite-1"],
                    "confidence": 0.82,
                    "limitations": [],
                    "used_evidence": ["ev-1"],
                }
            }
        )
    ).synthesize(
        task_id="task-1",
        run_id="run-1",
        context_id="ctx-1",
        report=report,
        evidence=[evidence],
        citations=[citation],
    )
    bad = Synthesizer(
        fabric=fake_fabric(
            {
                "synthesizer.answer": {
                    "answer": "Kernel v3 cites evidence.",
                    "citation_refs": ["cite-missing"],
                    "confidence": 0.82,
                    "limitations": [],
                    "used_evidence": ["ev-1"],
                }
            }
        )
    ).synthesize(
        task_id="task-1",
        run_id="run-1",
        context_id="ctx-1",
        report=report,
        evidence=[evidence],
        citations=[citation],
    )

    assert ok.status == "ok"
    assert ok.citation_refs == ["cite-1"]
    assert bad.status == "failed"
    assert bad.error == "unknown_citation_refs:cit\u0065-missing"


def test_phase5_timeout_provider_produces_failed_processor_result():
    journal = JournalStore.in_memory()

    outcome = timeout_fabric(journal=journal).run_json(
        task_type="planner.propose",
        task_id="task-timeout",
        run_id="run-timeout",
        context_id="ctx-timeout",
        prompt="timeout",
        schema=PLANNER_SCHEMA,
    )

    assert outcome.result.status == "failed"
    assert outcome.result.error == "TimeoutError"
    result_record = journal.records(task_id="task-timeout", kind="processor_result")[0]
    assert result_record.data["status"] == "failed"
    assert result_record.data["error"] == "TimeoutError"


def test_phase5_router_model_takes_precedence_over_provider_default():
    journal = JournalStore.in_memory()
    provider = FakeJsonProvider(
        {
            "action_id": "act-route-model",
            "kind": "respond",
            "name": None,
            "description": "respond",
            "payload": {"text": "ok"},
            "score": 1.0,
            "reasons": [],
            "side_effect_class": "none",
        }
    )
    provider.model = "provider-default-model"
    fabric = ProcessorFabric(
        providers={"fake_json": provider},
        router=ProcessorRouter(
            routes={
                "planner.propose": ProcessorRoute(
                    task_type="planner.propose",
                    provider="fake_json",
                    model="route-model",
                    timeout_seconds=30,
                )
            }
        ),
        journal=journal,
    )

    outcome = fabric.run_json(
        task_type="planner.propose",
        task_id="task-route",
        run_id="run-route",
        context_id="ctx-route",
        prompt="route model",
        schema=PLANNER_SCHEMA,
    )

    request = journal.records(task_id="task-route", kind="processor_request")[0]
    result = journal.records(task_id="task-route", kind="processor_result")[0]
    assert outcome.model == "route-model"
    assert outcome.request.parameters["model"] == "route-model"
    assert request.data["model"] == "route-model"
    assert result.data["model"] == "route-model"


def test_phase5_request_parameters_cannot_spoof_processor_route_metadata():
    journal = JournalStore.in_memory()
    fabric = fake_fabric(
        {
            "planner.propose": {
                "action_id": "act-safe-meta",
                "kind": "respond",
                "name": None,
                "description": "respond",
                "payload": {"text": "ok"},
                "score": 1.0,
                "reasons": [],
                "side_effect_class": "none",
            }
        },
        journal=journal,
    )

    outcome = fabric.run_json(
        task_type="planner.propose",
        task_id="task-spoof",
        run_id="run-spoof",
        context_id="ctx-spoof",
        prompt="spoof",
        schema=PLANNER_SCHEMA,
        parameters={
            "provider": "deepseek",
            "model": "expensive-live-model",
            "task_type": "synthesizer.answer",
            "timeout_seconds": 999,
        },
    )

    request = journal.records(task_id="task-spoof", kind="processor_request")[0]
    assert outcome.provider == "fake_json"
    assert outcome.model == "fake-json"
    assert request.data["task_type"] == "planner.propose"
    assert request.data["provider"] == "fake_json"
    assert request.data["model"] == "fake-json"
    assert request.data["parameters"]["timeout_seconds"] == 30


def test_phase5_secrets_do_not_appear_in_journal_context_or_trace(monkeypatch):
    secret = "phase5-secret-value"
    monkeypatch.setenv("DEEPSEEK_API_KEY", secret)
    journal = JournalStore.in_memory()
    fabric = ProcessorFabric(
        providers={"deepseek": DeepSeekProvider(enabled=False)},
        router=ProcessorRouter(default_provider="deepseek", default_model="deepseek-chat"),
        journal=journal,
    )

    fabric.run_json(
        task_type="planner.propose",
        task_id="task-secret",
        run_id="run-secret",
        context_id="ctx-secret",
        prompt="secret hygiene",
        schema=PLANNER_SCHEMA,
    )
    trace = TraceRenderer(journal).render_task("task-secret", verbose=True)
    encoded = json.dumps([record.to_dict() for record in journal.records(task_id="task-secret")], ensure_ascii=False)

    assert secret not in encoded
    assert "DEEPSEEK_API_KEY" not in encoded
    assert secret not in trace
    assert "DEEPSEEK_API_KEY" not in trace


def test_phase5_loop_controller_remains_tool_name_and_provider_agnostic():
    source = Path("kernel_v3/loop.py").read_text(encoding="utf-8")

    for forbidden in ["retrieval.run", "deepseek", "openai_compatible", "web_search", "page_open"]:
        assert forbidden not in source


def _context():
    return type(
        "TestContext",
        (),
        {
            "context_id": "ctx-1",
            "thread_key": "local:default",
            "event_ids": ["evt-1"],
            "memory_refs": [],
            "state": {"task_id": "task-1", "run_id": "run-1", "sections": []},
            "token_budget": 4096,
        },
    )()


def _respond(action_id: str, text: str) -> CandidateAction:
    return CandidateAction(
        action_id=action_id,
        kind="respond",
        name=None,
        description="respond",
        score=1.0,
        payload={"text": text},
        reasons=[],
        side_effect_class="none",
    )


def _retrieval_contracts():
    evidence = EvidenceItem(
        evidence_id="ev-1",
        goal_id="goal-1",
        span_id="span-1",
        document_id="doc-1",
        source_id="src-1",
        artifact_id="artifact-1",
        uri="https://example.test/one",
        title="One",
        text="Kernel v3 cites evidence.",
        score=1.0,
        payload_hash="hash-1",
    )
    citation = CitationItem(
        citation_id="cite-1",
        goal_id="goal-1",
        evidence_id="ev-1",
        artifact_id="artifact-1",
        uri="https://example.test/one",
        title="One",
        quote="Kernel v3 cites evidence.",
        span_start=0,
        span_end=25,
    )
    report = RetrievalReport(
        report_id="report-1",
        goal_id="goal-1",
        status="sufficient",
        query_plan_id="plan-1",
        search_attempt_ids=["search-1"],
        fetch_attempt_ids=["fetch-1"],
        evidence_ids=["ev-1"],
        citation_ids=["cite-1"],
        evaluation_id="eval-1",
        artifact_refs=["artifact-1"],
        preview="Kernel v3 cites evidence.",
    )
    return report, evidence, citation
