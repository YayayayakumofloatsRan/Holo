import json
from dataclasses import replace
from pathlib import Path

from kernel_v3.context import ContextCompiler
from kernel_v3.contracts import CandidateAction, Observation
from kernel_v3.journal import JournalStore
from kernel_v3.loop import LoopControllerV3
from kernel_v3.policy import PolicyGate
from kernel_v3.processors import (
    DEEPSEEK_V4_FLASH,
    DEEPSEEK_V4_PRO,
    EVALUATOR_SCHEMA,
    PLANNER_SCHEMA,
    PLANNER_PROMPT_CONTRACT,
    DeepSeekProvider,
    FakeJsonProvider,
    FakeMalformedJsonProvider,
    ModelEvaluator,
    ModelPlanner,
    ProcessorFabric,
    ProcessorRoute,
    ProcessorRouter,
    Synthesizer,
    deepseek_v4_semantic_scenarios,
    deepseek_v4_router,
    run_semantic_scenarios,
    scenario_report_payload,
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


def test_phase5_planner_contract_requires_explicit_handling_of_constrained_subrequests():
    lowered = PLANNER_PROMPT_CONTRACT.lower()

    assert "compound user requests" in lowered
    assert "multiple subrequests" in lowered
    assert "silently omitting" in lowered
    assert "never invent tools" in lowered


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
    policy = journal.records(task_id=result.task_id, kind="policy_decision")[0]
    assert policy.data["allowed"] is False
    assert policy.data["reason"] == "unregistered_tool"
    assert policy.data["constraints"]["tool_name"] == "unknown.operator"
    observation = journal.records(task_id=result.task_id, kind="observation")[0]
    assert observation.data["status"] == "blocked"
    assert observation.data["content"] == {"reason": "unregistered_tool"}


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


def test_phase5_evaluator_prompt_uses_observation_previews_not_raw_bodies():
    raw = "RAW_PROVIDER_EGRESS_OBSERVATION_" + ("x" * 900)
    provider = CapturingFakeJsonProvider(
        {
            "evaluator.assess": {
                "status": "final_answer_ready",
                "answer": "ok",
                "stop_reason": "completed",
                "missing_evidence": [],
            }
        }
    )
    evaluator = ModelEvaluator(
        fabric=ProcessorFabric(
            providers={"fake_json": provider},
            router=ProcessorRouter(default_provider="fake_json", default_model="fake-json"),
        )
    )

    evaluator.evaluate(
        _context(),
        Observation(
            observation_id="obs-raw",
            run_id="run-1",
            kind="tool_result",
            status="ok",
            source="tool:file.read",
            content={"path": "secret.txt", "text": raw},
            observed_at_ms=0,
            action_id="act-read",
            tool_call_id=None,
        ),
    )

    assert raw not in provider.last_prompt
    assert "text_preview" in provider.last_prompt
    assert "text_hash" in provider.last_prompt


def test_phase5_model_planner_redacts_secret_like_context_before_provider_and_journal():
    secret_url = "https://example.test/report?access_token=planner-secret-token-1234567890"
    journal = JournalStore.in_memory()
    provider = CapturingFakeJsonProvider(
        {
            "planner.propose": {
                "action_id": "act-redacted",
                "kind": "respond",
                "name": None,
                "description": "respond safely",
                "payload": {"text": "ok"},
                "score": 1.0,
                "reasons": [],
                "side_effect_class": "none",
            }
        }
    )
    planner = ModelPlanner(
        fabric=ProcessorFabric(
            providers={"fake_json": provider},
            router=ProcessorRouter(default_provider="fake_json", default_model="fake-json"),
            journal=journal,
        )
    )
    context = _context(
        state={
            "task_id": "task-secret-context",
            "run_id": "run-secret-context",
            "input_text": f"inspect {secret_url}",
            "sections": [{"name": "user_event", "records": [{"text": secret_url}]}],
        }
    )

    action = planner.propose(context)

    assert action.action_id == "act-redacted"
    assert "[REDACTED:SECRET]" in provider.last_prompt
    encoded = json.dumps([record.to_dict() for record in journal.records()], ensure_ascii=False)
    assert "planner-secret-token" not in provider.last_prompt
    assert "access_token" not in provider.last_prompt
    assert "planner-secret-token" not in encoded
    assert "access_token" not in encoded


def test_phase5_synthesizer_prompt_uses_evidence_and_citation_previews_not_raw_bodies():
    raw = "RAW_PROVIDER_EGRESS_EVIDENCE_" + ("y" * 900)
    report, evidence, citation = _retrieval_contracts()
    provider = CapturingFakeJsonProvider(
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

    answer = Synthesizer(
        fabric=ProcessorFabric(
            providers={"fake_json": provider},
            router=ProcessorRouter(default_provider="fake_json", default_model="fake-json"),
        )
    ).synthesize(
        task_id="task-1",
        run_id="run-1",
        context_id="ctx-1",
        report=report,
        evidence=[replace(evidence, text=raw)],
        citations=[replace(citation, quote=raw)],
    )

    assert answer.status == "ok"
    assert raw not in provider.last_prompt
    assert "text_preview" in provider.last_prompt
    assert "quote_preview" in provider.last_prompt


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


def test_phase5_deepseek_v4_router_profiles_assign_component_models_and_tuning():
    balanced = deepseek_v4_router(profile="balanced")
    planner = balanced.route("planner.propose")
    evaluator = balanced.route("evaluator.assess")
    synthesizer = balanced.route("synthesizer.answer")

    assert planner.model == DEEPSEEK_V4_FLASH
    assert planner.parameters["thinking"] == "disabled"
    assert evaluator.model == DEEPSEEK_V4_PRO
    assert evaluator.parameters["thinking"] == "enabled"
    assert evaluator.parameters["reasoning_effort"] == "high"
    assert synthesizer.model == DEEPSEEK_V4_PRO
    assert synthesizer.parameters["thinking"] == "disabled"


def test_phase5_deepseek_v4_router_exposes_user_reasoning_overrides():
    router = deepseek_v4_router(profile="balanced", thinking="enabled", reasoning_effort="max")

    planner = router.route("planner.propose")
    evaluator = router.route("evaluator.assess")
    synthesizer = router.route("synthesizer.answer")

    assert planner.parameters["thinking"] == "enabled"
    assert planner.parameters["reasoning_effort"] == "max"
    assert evaluator.parameters["thinking"] == "enabled"
    assert evaluator.parameters["reasoning_effort"] == "max"
    assert synthesizer.parameters["thinking"] == "enabled"
    assert synthesizer.parameters["reasoning_effort"] == "max"


def test_phase5_route_parameters_are_journaled_and_sent_to_provider_request():
    journal = JournalStore.in_memory()
    fabric = ProcessorFabric(
        providers={
            "fake_json": FakeJsonProvider(
                {
                    "action_id": "act-route-params",
                    "kind": "respond",
                    "name": None,
                    "description": "respond",
                    "payload": {"text": "ok"},
                    "score": 1.0,
                    "reasons": [],
                    "side_effect_class": "none",
                }
            )
        },
        router=ProcessorRouter(
            routes={
                "planner.propose": ProcessorRoute(
                    task_type="planner.propose",
                    provider="fake_json",
                    model="route-model",
                    timeout_seconds=30,
                    parameters={"thinking": "disabled", "max_tokens": 128},
                )
            }
        ),
        journal=journal,
    )

    outcome = fabric.run_json(
        task_type="planner.propose",
        task_id="task-route-params",
        run_id="run-route-params",
        context_id="ctx-route-params",
        prompt="route params",
        schema=PLANNER_SCHEMA,
    )

    request = journal.records(task_id="task-route-params", kind="processor_request")[0]
    assert outcome.request.parameters["thinking"] == "disabled"
    assert outcome.request.parameters["max_tokens"] == 128
    assert request.data["parameters"]["thinking"] == "disabled"
    assert request.data["parameters"]["max_tokens"] == 128


def test_phase5_deepseek_provider_payload_uses_component_route_tuning(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")

    class CapturingDeepSeekProvider(DeepSeekProvider):
        def __init__(self):
            super().__init__(enabled=True)
            self.payload = None

        def _post_json(self, url, api_key, payload, timeout_seconds):
            self.payload = dict(payload)
            return {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "status": "continue",
                                    "answer": None,
                                    "stop_reason": None,
                                    "missing_evidence": ["more evidence"],
                                }
                            )
                        }
                    }
                ],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            }

    provider = CapturingDeepSeekProvider()
    fabric = ProcessorFabric(
        providers={"deepseek": provider},
        router=deepseek_v4_router(profile="balanced"),
    )

    outcome = fabric.run_json(
        task_type="evaluator.assess",
        run_id="run-capture",
        context_id="ctx-capture",
        prompt="capture",
        schema=EVALUATOR_SCHEMA,
    )

    assert outcome.result.status == "ok"
    assert provider.payload["model"] == DEEPSEEK_V4_PRO
    assert provider.payload["thinking"] == {"type": "enabled"}
    assert provider.payload["reasoning_effort"] == "high"
    assert provider.payload["max_tokens"] == 768


def test_phase5_secrets_do_not_appear_in_journal_context_or_trace(monkeypatch):
    secret = "phase5-secret-value"
    monkeypatch.setenv("DEEPSEEK_API_KEY", secret)
    journal = JournalStore.in_memory()
    provider = DeepSeekProvider(enabled=False)
    fabric = ProcessorFabric(
        providers={"deepseek": provider},
        router=ProcessorRouter(default_provider="deepseek", default_model=provider.model),
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


def test_phase5_semantic_scenario_library_validates_fake_outputs():
    journal = JournalStore.in_memory()
    responses = {
        "planner.propose": [
            {
                "action_id": "act-live-retrieval",
                "kind": "tool",
                "name": "retrieval.run",
                "description": "retrieve",
                "payload": {"goal": "DeepSeek V4 API models", "query": "DeepSeek V4 API models"},
                "score": 0.9,
                "reasons": ["current evidence is required"],
                "side_effect_class": "read",
            },
            {
                "action_id": "act-live-clarify",
                "kind": "ask_user",
                "name": None,
                "description": "clarify",
                "payload": {"question": "Which file?"},
                "score": 0.9,
                "reasons": ["missing target"],
                "side_effect_class": "none",
            },
        ],
        "evaluator.assess": [
            {
                "status": "final_answer_ready",
                "answer": "DeepSeek V4 API exposes deepseek-v4-flash and deepseek-v4-pro.",
                "stop_reason": "completed",
                "missing_evidence": [],
            },
            {
                "status": "continue",
                "answer": None,
                "stop_reason": None,
                "missing_evidence": ["cited source"],
            },
        ],
        "synthesizer.answer": {
            "answer": "DeepSeek V4 API 的模型 ID 是 deepseek-v4-flash 和 deepseek-v4-pro。",
            "citation_refs": ["cite-v4-models"],
            "confidence": 0.9,
            "limitations": [],
            "used_evidence": ["ev-v4-models"],
        },
    }
    fabric = fake_fabric(responses, journal=journal)

    results = run_semantic_scenarios(
        fabric,
        task_id="task-scenarios",
        run_id="run-scenarios",
        context_id="ctx-scenarios",
        scenarios=deepseek_v4_semantic_scenarios(),
    )
    report = scenario_report_payload(results)

    assert report["status"] == "ok"
    assert report["scenario_count"] == 5
    assert report["passed"] == 5
    assert len(journal.records(task_id="task-scenarios", kind="processor_request")) == 5
    assert len(journal.records(task_id="task-scenarios", kind="processor_result")) == 5


def test_phase5_semantic_scenarios_do_not_embed_answer_key_json():
    for scenario in deepseek_v4_semantic_scenarios():
        payload = json.loads(scenario.prompt)

        assert "required_output" not in payload
        assert "acceptance_criteria" in payload
        assert isinstance(payload["acceptance_criteria"], list)
        assert payload["acceptance_criteria"]
        assert "required_output" not in scenario.prompt
        assert "act-live-retrieval" not in scenario.prompt
        assert "act-live-clarify" not in scenario.prompt


def test_phase5_loop_controller_remains_tool_name_and_provider_agnostic():
    source = Path("kernel_v3/loop.py").read_text(encoding="utf-8")

    for forbidden in ["retrieval.run", "deepseek", "openai_compatible", "web_search", "page_open"]:
        assert forbidden not in source


def _context(state=None):
    return type(
        "TestContext",
        (),
        {
            "context_id": "ctx-1",
            "thread_key": "local:default",
            "event_ids": ["evt-1"],
            "memory_refs": [],
            "state": state or {"task_id": "task-1", "run_id": "run-1", "sections": []},
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


class CapturingFakeJsonProvider(FakeJsonProvider):
    def __init__(self, responses):
        super().__init__(responses)
        self.last_prompt = ""

    def run(self, request):
        self.last_prompt = request.prompt
        return super().run(request)
