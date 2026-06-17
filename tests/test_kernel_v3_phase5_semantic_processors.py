import json
import time
from dataclasses import replace
from pathlib import Path

from kernel_v3 import cli
from kernel_v3.agent import analyze_goal_with_processor
from kernel_v3.context import ContextCompiler
from kernel_v3.contracts import CandidateAction, Observation, ProcessorRequest, ProcessorResult
from kernel_v3.interaction import guard_user_visible_text
from kernel_v3.journal import JournalStore
from kernel_v3.loop import LoopControllerV3
from kernel_v3.policy import PolicyGate
from kernel_v3.processors import (
    DEEPSEEK_V4_FLASH,
    DEEPSEEK_V4_PRO,
    EVALUATOR_SCHEMA,
    EVALUATOR_PROMPT_CONTRACT,
    MISSION_ASSESS_PROMPT_CONTRACT,
    PLANNER_SCHEMA,
    PLANNER_PROMPT_CONTRACT,
    PROCESSOR_SYSTEM_PROMPT,
    SEMANTIC_INTAKE_PROMPT_CONTRACT,
    SYNTHESIZER_PROMPT_CONTRACT,
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
from kernel_v3.processors.providers import _read_response_text_with_deadline
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


def test_phase5_processor_prompt_contracts_include_json_examples_for_model_imitation():
    contracts = [
        SEMANTIC_INTAKE_PROMPT_CONTRACT,
        PLANNER_PROMPT_CONTRACT,
        EVALUATOR_PROMPT_CONTRACT,
        SYNTHESIZER_PROMPT_CONTRACT,
    ]

    for contract in contracts:
        lowered = contract.lower()
        assert "example" in lowered
        assert "{" in contract and "}" in contract


def test_phase5_planner_and_evaluator_contracts_explain_toolchain_state_packet():
    combined = "\n".join([PLANNER_PROMPT_CONTRACT, EVALUATOR_PROMPT_CONTRACT]).lower()

    assert "context.state.toolchain_state" in combined
    assert "toolchain_presence" in combined
    assert "failed_tools" in combined
    assert "observation_diagnostics" in combined
    assert "issue_codes" in combined
    assert "repair_options" in combined
    assert "missing_value_examples" in combined
    assert "repeated_action_fingerprints" in combined
    assert "repeated_action_groups" in combined
    assert "payload_summary" in combined
    assert "post_final_record_count" in combined
    assert "not as host-selected semantic answers" in combined
    assert "observational only" in combined


def test_phase5_planner_and_evaluator_contracts_explain_finance_working_state_packet():
    combined = "\n".join([PLANNER_PROMPT_CONTRACT, EVALUATOR_PROMPT_CONTRACT]).lower()

    assert "context.state.finance_working_state" in combined
    assert "slot_frame" in combined
    assert "missing_slots" in combined
    assert "formula_trace_support" in combined
    assert "numeric_verification" in combined
    assert "repair_options" in combined
    assert "model still owns finance semantic binding" in combined


def test_phase5_roleplay_style_contract_avoids_parenthesized_stage_directions_by_default():
    combined = "\n".join([PROCESSOR_SYSTEM_PROMPT, PLANNER_PROMPT_CONTRACT, SYNTHESIZER_PROMPT_CONTRACT]).lower()

    assert "roleplay" in combined
    assert "parenthesized stage directions" in combined
    assert "unless the user explicitly" in combined


def test_phase5_processor_system_prompt_guides_visible_text_style_without_overriding_host_control():
    lowered = PROCESSOR_SYSTEM_PROMPT.lower()

    assert "user-visible text" in lowered
    assert "technical" in lowered
    assert "rigorous" in lowered
    assert "pragmatic" in lowered
    assert "ordinary small talk" in lowered
    assert "natural" in lowered
    assert "never overrides policy" in lowered
    assert "evidence" in lowered
    assert "default user-visible text to chinese" in lowered
    assert "generic agreement" in lowered
    assert "flattery" in lowered
    assert "specific failure" in lowered
    assert "concrete fix" in lowered
    assert "never begin user-visible text" in lowered
    assert "unless the next clause" not in lowered


def test_phase5_user_visible_text_contracts_avoid_generic_agreement_prefaces():
    combined = "\n".join([PROCESSOR_SYSTEM_PROMPT, PLANNER_PROMPT_CONTRACT, SYNTHESIZER_PROMPT_CONTRACT]).lower()

    assert "generic agreement" in combined
    assert "flattery" in combined
    assert "bug report" in combined or "reports a bug" in combined
    assert "concrete" in combined
    assert "you are right" in combined
    assert "never begin" in combined
    assert "unless the next clause" not in combined


def test_phase5_research_prompts_tell_model_to_judge_soft_gaps_like_researcher():
    combined = "\n".join([PLANNER_PROMPT_CONTRACT, EVALUATOR_PROMPT_CONTRACT, SYNTHESIZER_PROMPT_CONTRACT, MISSION_ASSESS_PROMPT_CONTRACT]).lower()

    assert "capable human researcher" in combined
    assert "soft missing facet" in combined
    assert "soft limitations" in combined or "soft auxiliary" in combined
    assert "not an automatic reason to loop forever" in combined


def test_phase5_finance_prompt_preserves_exact_metric_phrase_for_line_item_disambiguation():
    lowered = PLANNER_PROMPT_CONTRACT.lower()

    assert "exact requested metric phrase" in lowered
    assert "net revenues" in lowered
    assert "sales and other operating revenues" in lowered
    assert "derivative" in lowered
    assert "multiple candidate values" in lowered
    assert "competing evidence" in lowered
    assert "10-k statement table" in lowered


def test_phase5_finance_prompt_exposes_numeric_verifier_tool_example():
    lowered = PLANNER_PROMPT_CONTRACT.lower()

    assert "finance.verify_numeric" in lowered
    assert "draft finance answer numeric support" in lowered
    assert "formula_traces" in lowered
    assert "a draft answer exists" in lowered


def test_phase5_user_visible_text_guard_trims_only_stock_agreement_prefix():
    assert guard_user_visible_text("你说得对，这个 bug 在 prompt 层。") == "这个 bug 在 prompt 层。"
    assert guard_user_visible_text("You are right: this needs a host-side guard.") == "this needs a host-side guard."
    assert guard_user_visible_text("用户报告了“你说得对”这个坏习惯。") == "用户报告了“你说得对”这个坏习惯。"


def test_phase5_response_language_preference_is_sent_to_semantic_processor():
    provider = CapturingFakeJsonProvider(
        {
            "semantic.intake": {
                "primary_intent": "direct_answer",
                "suggested_mode": "direct_answer",
                "compound": False,
                "requires_clarification": False,
                "intents": [
                    {
                        "kind": "direct_answer",
                        "text": "answer",
                        "sequence_index": 1,
                        "required_capabilities": [],
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
        }
    )
    analyze_goal_with_processor(
        "who are you",
        fabric=ProcessorFabric(
            providers={"fake_json": provider},
            router=ProcessorRouter(default_provider="fake_json", default_model="fake-json"),
        ),
        task_id="task-lang",
        run_id="run-lang",
        context_id="ctx-lang",
        response_language="en",
    )

    assert '"response_language": "en"' in provider.last_prompt
    assert "interaction_preferences" in provider.last_prompt


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
    assert action.data["kind"] == "respond"
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


def test_phase5_synthesizer_repairs_missing_citation_refs_with_known_refs():
    report, evidence, citation = _retrieval_contracts()
    provider = CapturingFakeJsonProvider(
        {
            "synthesizer.answer": [
                {
                    "answer": "Kernel v3 cites evidence.",
                    "citation_refs": [],
                    "confidence": 0.2,
                    "limitations": [],
                    "used_evidence": ["ev-1"],
                },
                {
                    "answer": "Kernel v3 cites evidence.",
                    "citation_refs": ["cite-1"],
                    "confidence": 0.82,
                    "limitations": [],
                    "used_evidence": ["ev-1"],
                },
            ]
        }
    )
    journal = JournalStore.in_memory()

    answer = Synthesizer(
        fabric=ProcessorFabric(
            providers={"fake_json": provider},
            router=ProcessorRouter(default_provider="fake_json", default_model="fake-json"),
            journal=journal,
        )
    ).synthesize(
        task_id="task-synth-repair",
        run_id="run-synth-repair",
        context_id="ctx-synth-repair",
        report=report,
        evidence=[evidence],
        citations=[citation],
    )

    retry_prompt = json.loads(provider.prompts[-1])
    assert answer.status == "ok"
    assert answer.citation_refs == ["cite-1"]
    assert len(provider.prompts) == 2
    assert retry_prompt["required_citation_refs"] == ["cite-1"]
    assert retry_prompt["required_evidence_refs"] == ["ev-1"]
    assert "retry_instruction" in retry_prompt
    assert len(journal.records(task_id="task-synth-repair", kind="processor_request")) == 2


def test_phase5_synthesizer_repairs_unknown_evidence_refs_with_known_refs():
    report, evidence, citation = _retrieval_contracts()
    provider = CapturingFakeJsonProvider(
        {
            "synthesizer.answer": [
                {
                    "answer": "Kernel v3 cites evidence.",
                    "citation_refs": ["cite-1"],
                    "confidence": 0.2,
                    "limitations": [],
                    "used_evidence": ["ev-missing"],
                },
                {
                    "answer": "Kernel v3 cites evidence.",
                    "citation_refs": ["cite-1"],
                    "confidence": 0.82,
                    "limitations": [],
                    "used_evidence": ["ev-1"],
                },
            ]
        }
    )
    journal = JournalStore.in_memory()

    answer = Synthesizer(
        fabric=ProcessorFabric(
            providers={"fake_json": provider},
            router=ProcessorRouter(default_provider="fake_json", default_model="fake-json"),
            journal=journal,
        )
    ).synthesize(
        task_id="task-synth-ref-repair",
        run_id="run-synth-ref-repair",
        context_id="ctx-synth-ref-repair",
        report=report,
        evidence=[evidence],
        citations=[citation],
    )

    retry_prompt = json.loads(provider.prompts[-1])
    assert answer.status == "ok"
    assert answer.citation_refs == ["cite-1"]
    assert answer.used_evidence == ["ev-1"]
    assert len(provider.prompts) == 2
    assert retry_prompt["required_citation_refs"] == ["cite-1"]
    assert retry_prompt["required_evidence_refs"] == ["ev-1"]
    assert retry_prompt["repair_feedback"]["category"] == "unknown_evidence_refs"
    assert retry_prompt["repair_feedback"]["unknown_evidence_refs"] == ["ev-missing"]
    assert "used citation_refs or used_evidence ids" in retry_prompt["retry_instruction"]
    assert len(journal.records(task_id="task-synth-ref-repair", kind="processor_request")) == 2


def test_phase5_synthesizer_retries_invalid_json_once():
    report, evidence, citation = _retrieval_contracts()
    provider = MalformedThenJsonProvider(
        {
            "answer": "Kernel v3 cites evidence after JSON retry.",
            "citation_refs": ["cite-1"],
            "confidence": 0.81,
            "limitations": [],
            "used_evidence": ["ev-1"],
        }
    )
    journal = JournalStore.in_memory()

    answer = Synthesizer(
        fabric=ProcessorFabric(
            providers={"fake_repair": provider},
            router=ProcessorRouter(default_provider="fake_repair", default_model="fake-repair"),
            journal=journal,
        )
    ).synthesize(
        task_id="task-synth-json-repair",
        run_id="run-synth-json-repair",
        context_id="ctx-synth-json-repair",
        report=report,
        evidence=[evidence],
        citations=[citation],
    )

    retry_prompt = json.loads(provider.prompts[-1])
    assert answer.status == "ok"
    assert answer.answer == "Kernel v3 cites evidence after JSON retry."
    assert answer.citation_refs == ["cite-1"]
    assert len(provider.prompts) == 2
    assert "Previous synthesizer output was not valid JSON" in retry_prompt["retry_instruction"]
    assert retry_prompt["repair_feedback"]["schema"] == "holo.kernel_v3.synthesizer_repair_feedback.v1"
    assert retry_prompt["repair_feedback"]["category"] == "malformed_json"
    assert retry_prompt["repair_feedback"]["required_fields"] == [
        "answer",
        "citation_refs",
        "confidence",
        "limitations",
        "used_evidence",
    ]
    assert "Return exactly one JSON object" in retry_prompt["repair_feedback"]["repair_checklist"][0]
    results = journal.records(task_id="task-synth-json-repair", kind="processor_result")
    assert [item.data["status"] for item in results] == ["failed", "ok"]
    retry_request = journal.records(task_id="task-synth-json-repair", kind="processor_request")[-1]
    assert retry_request.data["parameters"]["repair_feedback_schema"] == "holo.kernel_v3.synthesizer_repair_feedback.v1"
    assert retry_request.data["parameters"]["repair_feedback_category"] == "malformed_json"


def test_phase5_synthesizer_compacts_prompt_before_processor_budget_limit():
    report, evidence, citation = _retrieval_contracts()
    evidence_items = [evidence]
    citations = [citation]
    for index in range(2, 82):
        item = replace(
            evidence,
            evidence_id=f"ev-{index}",
            span_id=f"span-{index}",
            document_id=f"doc-{index}",
            source_id=f"src-{index}",
            artifact_id=f"artifact-{index}",
            title=f"Evidence {index}",
            text=("large finance evidence text " * 160),
            payload_hash=f"hash-{index}",
        )
        evidence_items.append(item)
        citations.append(
            replace(
                citation,
                citation_id=f"cite-{index}",
                evidence_id=item.evidence_id,
                artifact_id=item.artifact_id,
                title=item.title,
                quote=("large citation quote " * 120),
            )
        )
    large_report = replace(
        report,
        evidence_ids=[item.evidence_id for item in evidence_items],
        citation_ids=[item.citation_id for item in citations],
        artifact_refs=[item.artifact_id for item in evidence_items],
        diagnostics={
            "task_goal": "Answer a finance filing question from the provided evidence.",
            "finance_fact_ledger": [
                {
                    "fact_id": f"fact-{index}",
                    "metric": "capital expenditure",
                    "value": str(index),
                    "metadata": {"raw": "x" * 1200, "statement": "cash flow statement"},
                }
                for index in range(160)
            ],
            "finance_formula_traces": [
                {"formula_id": f"formula-{index}", "result_value": str(index), "diagnostics": {"raw": "y" * 900}}
                for index in range(24)
            ],
            "search_summaries": [{"query": f"query {index}", "raw": "z" * 1400} for index in range(12)],
        },
    )
    provider = CapturingFakeJsonProvider(
        {
            "synthesizer.answer": {
                "answer": "Kernel v3 cites compact evidence.",
                "citation_refs": ["cite-1"],
                "confidence": 0.82,
                "limitations": [],
                "used_evidence": ["ev-1"],
            }
        }
    )
    journal = JournalStore.in_memory()
    max_prompt_chars = 60_000

    answer = Synthesizer(
        fabric=ProcessorFabric(
            providers={"fake_json": provider},
            router=ProcessorRouter(default_provider="fake_json", default_model="fake-json"),
            journal=journal,
        )
    ).synthesize(
        task_id="task-synth-budget",
        run_id="run-synth-budget",
        context_id="ctx-synth-budget",
        report=large_report,
        evidence=evidence_items,
        citations=citations,
        processor_budget={"max_prompt_chars_per_call": max_prompt_chars},
    )

    prompt_payload = json.loads(provider.last_prompt)
    request = journal.records(task_id="task-synth-budget", kind="processor_request")[0]
    params = request.data["parameters"]
    assert answer.status == "ok"
    assert len(provider.last_prompt) <= max_prompt_chars
    assert params["synthesis_context_compaction"] == "budgeted"
    assert params["synthesis_original_prompt_chars"] > params["synthesis_compact_prompt_chars"]
    assert prompt_payload["retrieval_report"]["diagnostics"]["synthesis_budget_compaction"]["host_role"]
    assert len(prompt_payload["required_evidence_refs"]) < len(evidence_items)
    assert "cite-1" in prompt_payload["required_citation_refs"]


def test_phase5_synthesizer_salvages_answer_text_after_json_repair_failure():
    report, evidence, citation = _retrieval_contracts()
    provider = AlwaysMalformedAnswerProvider(
        '{"answer": "SEC filing evidence is insufficient to identify the segment. '
        'The answer should be treated as a limitation.", "citation_refs": ["cite-1"], '
    )
    journal = JournalStore.in_memory()

    answer = Synthesizer(
        fabric=ProcessorFabric(
            providers={"fake_salvage": provider},
            router=ProcessorRouter(default_provider="fake_salvage", default_model="fake-salvage"),
            journal=journal,
        )
    ).synthesize(
        task_id="task-synth-json-salvage",
        run_id="run-synth-json-salvage",
        context_id="ctx-synth-json-salvage",
        report=report,
        evidence=[evidence],
        citations=[citation],
    )

    assert answer.status == "ok"
    assert "SEC filing evidence is insufficient" in str(answer.answer)
    assert answer.citation_refs == ["cite-1"]
    assert answer.used_evidence == ["ev-1"]
    assert "synthesizer_json_salvaged" in answer.limitations
    assert len(provider.prompts) == 2


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
    assert outcome.result.output["error_type"] == "TimeoutError"
    assert outcome.result.output["error_message_preview"] == "fake processor timeout"
    result_record = journal.records(task_id="task-timeout", kind="processor_result")[0]
    assert result_record.data["status"] == "failed"
    assert result_record.data["error"] == "TimeoutError"
    assert result_record.data["output"]["error_message_preview"] == "fake processor timeout"


def test_phase5_processor_fabric_short_circuits_repeated_provider_availability_failure():
    class NetworkFailingProvider:
        name = "deepseek"
        model = "deepseek-v4-flash"

        def __init__(self) -> None:
            self.calls = 0

        def run(self, request: ProcessorRequest) -> ProcessorResult:
            self.calls += 1
            return ProcessorResult(
                result_id=f"result-{request.request_id}",
                request_id=request.request_id,
                status="failed",
                output={
                    "provider": self.name,
                    "model": self.model,
                    "error_message_preview": "deepseek network error: temporary failure in name resolution",
                },
                usage={},
                error="RuntimeError",
            )

    provider = NetworkFailingProvider()
    journal = JournalStore.in_memory()
    fabric = ProcessorFabric(
        providers={"deepseek": provider},
        router=ProcessorRouter(default_provider="deepseek", default_model="deepseek-v4-flash"),
        journal=journal,
    )

    first = fabric.run_json(
        task_type="planner.propose",
        task_id="task-circuit",
        run_id="run-circuit",
        context_id="ctx-circuit-1",
        prompt="first provider failure",
        schema=PLANNER_SCHEMA,
    )
    second = fabric.run_json(
        task_type="evaluator.assess",
        task_id="task-circuit",
        run_id="run-circuit",
        context_id="ctx-circuit-2",
        prompt="second call should short circuit",
        schema=EVALUATOR_SCHEMA,
    )

    assert first.result.status == "failed"
    assert second.result.status == "failed"
    assert second.result.error == "provider_circuit_open"
    assert provider.calls == 1
    result_records = journal.records(task_id="task-circuit", kind="processor_result")
    assert result_records[-1].data["output"]["circuit"] == "provider_unavailable"
    assert result_records[-1].data["duration_ms"] == 0


def test_phase5_provider_circuit_is_scoped_by_model_not_whole_provider():
    class MixedModelProvider:
        name = "deepseek"
        model = DEEPSEEK_V4_FLASH

        def __init__(self) -> None:
            self.calls: list[str] = []

        def run(self, request: ProcessorRequest) -> ProcessorResult:
            model = str(request.parameters.get("model") or self.model)
            self.calls.append(model)
            if model == DEEPSEEK_V4_PRO:
                return ProcessorResult(
                    result_id=f"result-{request.request_id}",
                    request_id=request.request_id,
                    status="failed",
                    output={
                        "provider": self.name,
                        "model": model,
                        "error_message_preview": "deepseek timeout after 30s while reading response",
                    },
                    usage={},
                    error="RuntimeError",
                )
            text = json.dumps(
                {
                    "status": "final_answer_ready",
                    "answer": "flash recovered",
                    "stop_reason": "completed",
                    "missing_evidence": [],
                },
                ensure_ascii=False,
            )
            return ProcessorResult(
                result_id=f"result-{request.request_id}",
                request_id=request.request_id,
                status="ok",
                output={"text": text, "provider": self.name, "model": model},
                usage={},
                error=None,
            )

    provider = MixedModelProvider()
    router = ProcessorRouter(default_provider="deepseek", default_model=DEEPSEEK_V4_FLASH)
    router.set_route("task.compile", model=DEEPSEEK_V4_PRO)
    router.set_route("finance.slot_bind", model=DEEPSEEK_V4_FLASH)
    journal = JournalStore.in_memory()
    fabric = ProcessorFabric(providers={"deepseek": provider}, router=router, journal=journal)

    first = fabric.run_json(
        task_type="task.compile",
        task_id="task-circuit-model",
        run_id="run-circuit-model",
        context_id="ctx-pro",
        prompt="pro call times out",
        schema=PLANNER_SCHEMA,
    )
    second = fabric.run_json(
        task_type="finance.slot_bind",
        task_id="task-circuit-model",
        run_id="run-circuit-model",
        context_id="ctx-flash",
        prompt="flash call should still run",
        schema=EVALUATOR_SCHEMA,
    )
    third = fabric.run_json(
        task_type="task.compile",
        task_id="task-circuit-model",
        run_id="run-circuit-model",
        context_id="ctx-pro-2",
        prompt="same pro model should short circuit",
        schema=PLANNER_SCHEMA,
    )

    assert first.result.status == "failed"
    assert first.result.error == "RuntimeError"
    assert second.result.status == "ok"
    assert second.parsed["answer"] == "flash recovered"
    assert third.result.status == "failed"
    assert third.result.error == "provider_circuit_open"
    assert provider.calls == [DEEPSEEK_V4_PRO, DEEPSEEK_V4_FLASH]
    result_records = journal.records(task_id="task-circuit-model", kind="processor_result")
    assert result_records[-1].data["output"]["previous_model"] == DEEPSEEK_V4_PRO


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


def test_phase5_model_planner_prompt_preserves_compact_toolchain_state():
    journal = JournalStore.in_memory()
    provider = CapturingFakeJsonProvider(
        {
            "planner.propose": {
                "action_id": "act-toolchain-aware",
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
            "task_id": "task-toolchain-prompt",
            "run_id": "run-toolchain-prompt",
            "input_text": "Continue the finance task.",
            "toolchain_state": {
                "schema": "holo.kernel_v3.toolchain_state.v1",
                "toolchain_presence": {"retrieval": True, "calculator": True, "finance_verify_numeric": False},
                "failed_tools": [{"source": "tool:retrieval.run", "status": "failed", "error": "network_failed"}],
                "recent_tool_observations": [
                    {
                        "source": "tool:finance.verify_numeric",
                        "status": "ok",
                        "observation_diagnostics": {
                            "verifier_status": "failed",
                            "issue_codes": ["unsupported_answer_number"],
                            "repair_options": ["ask synthesis to remove unsupported numbers"],
                            "missing_value_examples": [
                                {"raw": "$12 million", "value": "12000000", "unit": "million", "slot": "revenue"}
                            ],
                        },
                    }
                ],
                "recent_tool_actions": [
                    {
                        "tool": "calculator.compute",
                        "action_id": "act-calc",
                        "payload_fingerprint": "fp-123",
                        "payload_summary": {
                            "formula_name": "gross_margin",
                            "variable_names": ["gross_profit", "revenue"],
                            "expression_fingerprint": "expr-123",
                        },
                    }
                ],
                "repeated_action_fingerprints": ["fp-123"],
                "repeated_action_groups": [
                    {
                        "tool": "calculator.compute",
                        "payload_fingerprint": "fp-123",
                        "attempt_count": 2,
                        "payload_summary": {
                            "formula_name": "gross_margin",
                            "variable_names": ["gross_profit", "revenue"],
                        },
                        "latest_observation_status": "ok",
                    }
                ],
                "post_final_record_count": 0,
                "host_boundary": "observational compact state only; model still chooses the next action",
            },
            "sections": [],
        }
    )

    action = planner.propose(context)
    prompt_payload = json.loads(provider.last_prompt)

    assert action.action_id == "act-toolchain-aware"
    toolchain = prompt_payload["context"]["state"]["toolchain_state"]
    assert toolchain["toolchain_presence"]["retrieval"] is True
    assert toolchain["toolchain_presence"]["calculator"] is True
    assert toolchain["failed_tools"][0]["source"] == "tool:retrieval.run"
    assert toolchain["recent_tool_observations"][0]["observation_diagnostics"]["issue_codes"] == [
        "unsupported_answer_number"
    ]
    assert toolchain["recent_tool_observations"][0]["observation_diagnostics"]["repair_options"] == [
        "ask synthesis to remove unsupported numbers"
    ]
    assert toolchain["repeated_action_fingerprints"] == ["fp-123"]
    assert toolchain["recent_tool_actions"][0]["payload_summary"]["formula_name"] == "gross_margin"
    assert toolchain["repeated_action_groups"][0]["attempt_count"] == 2
    assert "network_failed" in provider.last_prompt
    assert "observation_diagnostics" in provider.last_prompt
    assert "unsupported_answer_number" in provider.last_prompt
    assert "$12 million" in provider.last_prompt
    assert "payload_fingerprint" in provider.last_prompt
    assert "payload_summary" in provider.last_prompt


def test_phase5_model_planner_prompt_omits_empty_toolchain_state():
    journal = JournalStore.in_memory()
    provider = CapturingFakeJsonProvider(
        {
            "planner.propose": {
                "action_id": "act-no-toolchain",
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
            "task_id": "task-no-toolchain-prompt",
            "run_id": "run-no-toolchain-prompt",
            "input_text": "hi",
            "toolchain_state": {},
            "sections": [],
        }
    )

    action = planner.propose(context)
    prompt_payload = json.loads(provider.last_prompt)

    assert action.action_id == "act-no-toolchain"
    assert "toolchain_state" not in prompt_payload["context"]["state"]
    assert "holo.kernel_v3.toolchain_state.v1" not in provider.last_prompt


def test_phase5_model_planner_prompt_preserves_compact_finance_working_state():
    journal = JournalStore.in_memory()
    provider = CapturingFakeJsonProvider(
        {
            "planner.propose": {
                "action_id": "act-finance-state-aware",
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
            "task_id": "task-finance-state-prompt",
            "run_id": "run-finance-state-prompt",
            "input_text": "Continue the finance task.",
            "finance_working_state": {
                "schema": "holo.kernel_v3.finance_working_state.v1",
                "fact_count": 2,
                "facts": [{"fact_id": "finfact-revenue", "metric": "revenue", "value": "1000"}],
                "slot_frame": {"task_type": "compute", "missing_slots": ["margin"]},
                "slot_bind": {
                    "decision": "ready",
                    "period_basis": [{"slot_name": "revenue", "selected_period": "FY2024"}],
                    "line_item_basis": [{"slot_name": "revenue", "selected_line_item": "Revenue"}],
                },
                "formula_traces": [{"formula_id": "formula-margin", "result_value": "0.4"}],
                "formula_trace_support": [{"formula_id": "formula-margin", "citation_refs": ["cite-revenue"]}],
                "numeric_verification": {
                    "status": "failed",
                    "issue_codes": ["unsupported_answer_number"],
                    "repair_options": ["ask synthesis to remove unsupported numbers"],
                },
                "host_boundary": "observational finance working state only; the model owns metric binding",
            },
            "sections": [],
        }
    )

    action = planner.propose(context)
    prompt_payload = json.loads(provider.last_prompt)

    assert action.action_id == "act-finance-state-aware"
    finance_state = prompt_payload["context"]["state"]["finance_working_state"]
    assert finance_state["fact_count"] == 2
    assert finance_state["facts"][0]["metric"] == "revenue"
    assert finance_state["slot_frame"]["missing_slots"] == ["margin"]
    assert finance_state["slot_bind"]["period_basis"][0]["selected_period"] == "FY2024"
    assert finance_state["slot_bind"]["line_item_basis"][0]["selected_line_item"] == "Revenue"
    assert finance_state["formula_trace_support"][0]["citation_refs"] == ["cite-revenue"]
    assert finance_state["numeric_verification"]["issue_codes"] == ["unsupported_answer_number"]
    assert finance_state["numeric_verification"]["repair_options"] == ["ask synthesis to remove unsupported numbers"]
    assert "RAW_PROVIDER_BODY_SHOULD_NOT_LEAK" not in provider.last_prompt


def test_phase5_model_evaluator_prompt_preserves_compact_finance_working_state():
    journal = JournalStore.in_memory()
    provider = CapturingFakeJsonProvider(
        {
            "evaluator.assess": {
                "status": "continue",
                "answer": None,
                "stop_reason": None,
                "missing_evidence": ["verify_margin"],
                "reason": "finance state shows verifier issue",
            }
        }
    )
    evaluator = ModelEvaluator(
        fabric=ProcessorFabric(
            providers={"fake_json": provider},
            router=ProcessorRouter(default_provider="fake_json", default_model="fake-json"),
            journal=journal,
        )
    )
    context = _context(
        state={
            "task_id": "task-finance-eval-prompt",
            "run_id": "run-finance-eval-prompt",
            "input_text": "Evaluate the latest finance observation.",
            "finance_working_state": {
                "schema": "holo.kernel_v3.finance_working_state.v1",
                "fact_count": 2,
                "facts": [{"fact_id": "finfact-revenue", "metric": "revenue", "value": "1000"}],
                "slot_frame": {"task_type": "compute", "missing_slots": ["margin"]},
                "slot_bind": {
                    "decision": "ready",
                    "period_basis": [{"slot_name": "revenue", "selected_period": "FY2024"}],
                    "line_item_basis": [{"slot_name": "revenue", "selected_line_item": "Revenue"}],
                },
                "formula_traces": [{"formula_id": "formula-margin", "result_value": "0.4"}],
                "formula_trace_support": [{"formula_id": "formula-margin", "citation_refs": ["cite-revenue"]}],
                "numeric_verification": {
                    "status": "failed",
                    "issue_codes": ["unsupported_answer_number"],
                    "repair_options": ["ask synthesis to remove unsupported numbers"],
                },
                "host_boundary": "observational finance working state only; the model owns metric binding",
            },
            "sections": [],
        }
    )
    observation = Observation(
        observation_id="obs-finance-eval",
        run_id="run-finance-eval-prompt",
        kind="tool_result",
        status="ok",
        source="tool:calculator.compute",
        content={"formula_trace": {"formula_id": "formula-margin", "result_value": "0.4"}},
        observed_at_ms=0,
        action_id="act-calc",
        tool_call_id=None,
    )

    feedback = evaluator.evaluate(context, observation)
    prompt_payload = json.loads(provider.last_prompt)

    assert feedback.status == "continue"
    finance_state = prompt_payload["context"]["state"]["finance_working_state"]
    assert finance_state["fact_count"] == 2
    assert finance_state["slot_bind"]["period_basis"][0]["selected_period"] == "FY2024"
    assert finance_state["slot_bind"]["line_item_basis"][0]["selected_line_item"] == "Revenue"
    assert finance_state["formula_trace_support"][0]["citation_refs"] == ["cite-revenue"]
    assert finance_state["numeric_verification"]["issue_codes"] == ["unsupported_answer_number"]
    assert finance_state["numeric_verification"]["repair_options"] == ["ask synthesis to remove unsupported numbers"]
    assert prompt_payload["observation"]["source"] == "tool:calculator.compute"


def test_phase5_model_planner_prompt_omits_empty_finance_working_state():
    journal = JournalStore.in_memory()
    provider = CapturingFakeJsonProvider(
        {
            "planner.propose": {
                "action_id": "act-generic-state-aware",
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
            "task_id": "task-generic-state-prompt",
            "run_id": "run-generic-state-prompt",
            "input_text": "Summarize the current document.",
            "finance_working_state": {},
            "sections": [],
        }
    )

    action = planner.propose(context)
    prompt_payload = json.loads(provider.last_prompt)

    assert action.action_id == "act-generic-state-aware"
    assert "finance_working_state" not in prompt_payload["context"]["state"]
    assert "holo.kernel_v3.finance_working_state.v1" not in provider.last_prompt


def test_phase5_synthesizer_prompt_uses_evidence_and_citation_previews_not_raw_bodies():
    raw = "RAW_PROVIDER_EGRESS_EVIDENCE_" + ("y" * 6000)
    tail = "SYNTHESIS_PREVIEW_TAIL_MARKER"
    report, evidence, citation = _retrieval_contracts()
    report = replace(
        report,
        diagnostics={
            **report.diagnostics,
            "task_goal": "回答 README 中的两个明确问题：当前主线是什么，旧 stage 是否还是施工对象。",
            "interaction_preferences": {"response_language": "zh"},
        },
    )
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
    prompt_payload = json.loads(provider.last_prompt)
    assert list(prompt_payload)[:3] == ["contract", "answer_requirements", "task_goal"]
    assert raw not in provider.last_prompt
    assert "task_goal" in provider.last_prompt
    assert '"response_language":"zh"' in provider.last_prompt
    assert "旧 stage 是否还是施工对象" in provider.last_prompt
    assert "Answer every explicit question" in provider.last_prompt
    assert "$193.414 billion" in provider.last_prompt
    assert "Chinese 百万" in provider.last_prompt
    assert "generic industry thresholds" in provider.last_prompt
    assert "comparison cutoffs" in provider.last_prompt
    assert "rule-of-thumb numbers" in provider.last_prompt
    assert "capital intensity" in provider.last_prompt
    assert "source-backed threshold" in provider.last_prompt
    assert "begin with one short English core answer sentence" in provider.last_prompt
    assert "adjacent revenue metrics" in provider.last_prompt
    assert "RevenueFromContractWithCustomerExcludingAssessedTax" in provider.last_prompt
    assert "broader subtotal that explicitly includes other income" in provider.last_prompt
    assert "Not separately itemized" in provider.last_prompt
    assert "must start with" in provider.last_prompt
    assert "Not separately itemized;" in provider.last_prompt
    assert "Do not headline a substitute numeric value" in provider.last_prompt
    assert "Not available in the provided evidence;" in provider.last_prompt
    assert "corrected actual value" in provider.last_prompt
    assert "text_preview" in provider.last_prompt
    assert "quote_preview" in provider.last_prompt

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
    Synthesizer(
        fabric=ProcessorFabric(
            providers={"fake_json": provider},
            router=ProcessorRouter(default_provider="fake_json", default_model="fake-json"),
        )
    ).synthesize(
        task_id="task-1",
        run_id="run-1",
        context_id="ctx-1",
        report=report,
        evidence=[replace(evidence, text=("e" * 900) + tail)],
        citations=[replace(citation, quote=("c" * 900) + tail)],
    )

    assert tail in provider.last_prompt


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
    assert "reasoning_effort" not in planner.parameters
    assert planner.timeout_seconds == 60
    assert evaluator.model == DEEPSEEK_V4_FLASH
    assert evaluator.parameters["thinking"] == "disabled"
    assert "reasoning_effort" not in evaluator.parameters
    assert evaluator.timeout_seconds == 60
    assert synthesizer.model == DEEPSEEK_V4_FLASH
    assert synthesizer.parameters["thinking"] == "disabled"
    assert "reasoning_effort" not in synthesizer.parameters
    assert synthesizer.timeout_seconds == 60

    quality = deepseek_v4_router(profile="quality")
    quality_planner = quality.route("planner.propose")
    assert quality_planner.model == DEEPSEEK_V4_PRO
    assert quality_planner.parameters["thinking"] == "enabled"
    assert quality_planner.parameters["reasoning_effort"] == "high"
    assert quality_planner.timeout_seconds == 90


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


def test_phase5_deepseek_v4_router_accepts_medium_reasoning_override():
    router = deepseek_v4_router(profile="quality", thinking="enabled", reasoning_effort="medium")

    evaluator = router.route("evaluator.assess")

    assert evaluator.parameters["thinking"] == "enabled"
    assert evaluator.parameters["reasoning_effort"] == "medium"


def test_phase5_deepseek_v4_router_locks_explicit_model_override():
    router = deepseek_v4_router(profile="balanced", model=DEEPSEEK_V4_PRO)

    planner = router.route("planner.propose")
    evaluator = router.route("evaluator.assess")

    assert planner.model == DEEPSEEK_V4_PRO
    assert planner.parameters["model_locked"] is True
    assert evaluator.model == DEEPSEEK_V4_PRO
    assert evaluator.parameters["model_locked"] is True


def test_phase5_deepseek_v4_router_can_use_provider_default_output_tokens_and_temperature():
    router = deepseek_v4_router(
        profile="balanced",
        max_output_tokens="provider",
        temperature=0.2,
    )

    planner = router.route("planner.propose")

    assert "max_tokens" not in planner.parameters
    assert planner.parameters["temperature"] == 0.2


def test_phase5_deepseek_v4_auto_route_budgets_are_not_truncation_prone():
    router = deepseek_v4_router(profile="fast", max_output_tokens="auto")

    planner = router.route("planner.propose")
    synthesizer = router.route("synthesizer.answer")

    assert planner.model == DEEPSEEK_V4_FLASH
    assert planner.parameters["thinking"] == "disabled"
    assert planner.parameters["max_tokens"] >= 2048
    assert synthesizer.model == DEEPSEEK_V4_FLASH
    assert synthesizer.parameters["thinking"] == "disabled"
    assert synthesizer.parameters["max_tokens"] >= 4096


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
    assert provider.payload["model"] == DEEPSEEK_V4_FLASH
    assert provider.payload["thinking"] == {"type": "disabled"}
    assert "reasoning_effort" not in provider.payload
    assert "max_tokens" not in provider.payload
    assert provider.payload["temperature"] == 0.0


def test_phase5_deepseek_provider_retries_transient_network_errors(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")

    class FlakyDeepSeekProvider(DeepSeekProvider):
        def __init__(self):
            super().__init__(enabled=True, max_retries=1)
            self.calls = 0

        def _post_json(self, url, api_key, payload, timeout_seconds):
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("deepseek network error: [SSL: UNEXPECTED_EOF_WHILE_READING] eof occurred")
            return {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "action_id": "act-retry-ok",
                                    "kind": "respond",
                                    "name": None,
                                    "description": "respond after retry",
                                    "payload": {"text": "ok"},
                                    "score": 0.9,
                                    "reasons": ["transient network retry succeeded"],
                                    "side_effect_class": "none",
                                }
                            )
                        }
                    }
                ],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            }

    provider = FlakyDeepSeekProvider()
    fabric = ProcessorFabric(
        providers={"deepseek": provider},
        router=deepseek_v4_router(profile="balanced"),
    )

    outcome = fabric.run_json(
        task_type="planner.propose",
        run_id="run-retry",
        context_id="ctx-retry",
        prompt="retry transient provider error",
        schema=PLANNER_SCHEMA,
    )

    assert outcome.result.status == "ok"
    assert provider.calls == 2


def test_deepseek_provider_retries_incomplete_read_errors(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")

    class FlakyIncompleteReadProvider(DeepSeekProvider):
        def __init__(self):
            super().__init__(enabled=True, max_retries=2)
            self.calls = 0

        def _post_json(self, url, api_key, payload, timeout_seconds):
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("deepseek network error: IncompleteRead: IncompleteRead(0 bytes read)")
            return {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "action_id": "act-incomplete-read-ok",
                                    "kind": "respond",
                                    "name": None,
                                    "description": "respond after incomplete read retry",
                                    "payload": {"text": "ok"},
                                    "score": 0.9,
                                    "reasons": ["incomplete read retry succeeded"],
                                    "side_effect_class": "none",
                                }
                            )
                        }
                    }
                ],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            }

    provider = FlakyIncompleteReadProvider()
    fabric = ProcessorFabric(
        providers={"deepseek": provider},
        router=deepseek_v4_router(profile="balanced"),
    )

    outcome = fabric.run_json(
        task_type="planner.propose",
        run_id="run-incomplete-read",
        context_id="ctx-incomplete-read",
        prompt="retry incomplete read provider error",
        schema=PLANNER_SCHEMA,
    )

    assert outcome.result.status == "ok"
    assert provider.calls == 2


def test_phase5_deepseek_provider_does_not_retry_bad_request(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")

    class BadRequestDeepSeekProvider(DeepSeekProvider):
        def __init__(self):
            super().__init__(enabled=True, max_retries=2)
            self.calls = 0

        def _post_json(self, url, api_key, payload, timeout_seconds):
            self.calls += 1
            raise RuntimeError("deepseek HTTP 400: bad request")

    journal = JournalStore.in_memory()
    provider = BadRequestDeepSeekProvider()
    fabric = ProcessorFabric(
        providers={"deepseek": provider},
        router=deepseek_v4_router(profile="balanced"),
        journal=journal,
    )

    outcome = fabric.run_json(
        task_type="planner.propose",
        task_id="task-bad-request",
        run_id="run-bad-request",
        context_id="ctx-bad-request",
        prompt="do not retry bad request",
        schema=PLANNER_SCHEMA,
    )

    assert outcome.result.status == "failed"
    assert provider.calls == 1
    result = journal.records(task_id="task-bad-request", kind="processor_result")[0]
    assert result.data["output"]["error_message_preview"].startswith("deepseek HTTP 400")


def test_phase5_adaptive_generation_raises_reasoning_for_large_quality_planner(monkeypatch):
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
                                    "action_id": "act-adaptive",
                                    "kind": "respond",
                                    "name": None,
                                    "description": "adaptive response",
                                    "payload": {"text": "ok"},
                                    "score": 0.9,
                                    "reasons": ["adaptive generation"],
                                    "side_effect_class": "none",
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
        router=deepseek_v4_router(
            profile="balanced",
            max_output_tokens="provider",
            generation_mode="auto",
            latency_target="quality",
        ),
    )

    outcome = fabric.run_json(
        task_type="planner.propose",
        run_id="run-adaptive-quality",
        context_id="ctx-adaptive-quality",
        prompt="large planner context\n" + ("x" * 25_000),
        schema=PLANNER_SCHEMA,
    )

    assert outcome.result.status == "ok"
    assert outcome.request.parameters["generation_policy"]["mode"] == "auto"
    assert outcome.request.parameters["generation_policy"]["assessment"]["complexity_band"] == "large"
    assert outcome.request.parameters["model"] == DEEPSEEK_V4_PRO
    assert outcome.request.parameters["thinking"] == "enabled"
    assert outcome.request.parameters["reasoning_effort"] == "high"
    assert outcome.request.parameters["timeout_seconds"] == 120
    assert provider.payload["model"] == DEEPSEEK_V4_PRO
    assert provider.payload["thinking"] == {"type": "enabled"}
    assert provider.payload["reasoning_effort"] == "high"
    assert provider.payload["temperature"] == 0.0
    assert "max_tokens" not in provider.payload


def test_phase5_adaptive_generation_keeps_large_balanced_planner_on_flash(monkeypatch):
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
                                    "action_id": "act-large-balanced",
                                    "kind": "respond",
                                    "name": None,
                                    "description": "large balanced response",
                                    "payload": {"text": "ok"},
                                    "score": 0.9,
                                    "reasons": ["large balanced generation"],
                                    "side_effect_class": "none",
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
        router=deepseek_v4_router(
            profile="balanced",
            max_output_tokens="provider",
            generation_mode="auto",
            latency_target="balanced",
        ),
    )

    outcome = fabric.run_json(
        task_type="planner.propose",
        run_id="run-large-balanced",
        context_id="ctx-large-balanced",
        prompt="large balanced planner context\n" + ("x" * 25_000),
        schema=PLANNER_SCHEMA,
    )

    assert outcome.result.status == "ok"
    assert outcome.request.parameters["generation_policy"]["assessment"]["complexity_band"] == "large"
    assert outcome.request.parameters["model"] == DEEPSEEK_V4_FLASH
    assert outcome.request.parameters["thinking"] == "disabled"
    assert "reasoning_effort" not in outcome.request.parameters
    assert outcome.request.parameters["timeout_seconds"] == 60
    assert provider.payload["model"] == DEEPSEEK_V4_FLASH
    assert provider.payload["thinking"] == {"type": "disabled"}
    assert "reasoning_effort" not in provider.payload


def test_phase5_adaptive_generation_respects_explicit_thinking_override(monkeypatch):
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
                                    "missing_evidence": ["evidence"],
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
        router=deepseek_v4_router(
            profile="quality",
            thinking="disabled",
            generation_mode="auto",
            latency_target="thorough",
        ),
    )

    outcome = fabric.run_json(
        task_type="evaluator.assess",
        run_id="run-adaptive-locked",
        context_id="ctx-adaptive-locked",
        prompt="evaluator context",
        schema=EVALUATOR_SCHEMA,
    )

    assert outcome.result.status == "ok"
    assert outcome.request.parameters["generation_policy"]["thinking_locked"] is True
    assert outcome.request.parameters["thinking"] == "disabled"
    assert "reasoning_effort" not in outcome.request.parameters
    assert outcome.request.parameters["timeout_seconds"] == 180
    assert provider.payload["thinking"] == {"type": "disabled"}
    assert "reasoning_effort" not in provider.payload


def test_phase5_deepseek_provider_packet_preview_shows_http_body_without_secrets(monkeypatch):
    secret = "packet-preview-secret"
    monkeypatch.setenv("DEEPSEEK_API_KEY", secret)
    provider = DeepSeekProvider(enabled=True)
    request = ProcessorRequest(
        request_id="proc-preview",
        run_id="run-preview",
        processor="planner.propose",
        prompt='{"contract":"Return JSON","dialogue":[{"role":"user","content":"你是谁"}]}',
        context_id="ctx-preview",
        parameters={
            "task_type": "planner.propose",
            "provider": "deepseek",
            "model": DEEPSEEK_V4_FLASH,
            "thinking": "disabled",
            "reasoning_effort": "high",
            "max_tokens": 256,
            "timeout_seconds": 30,
        },
    )

    packet = provider.packet_preview(request)
    encoded = json.dumps(packet, ensure_ascii=False)

    assert packet["method"] == "POST"
    assert packet["headers"]["Authorization"] == "Bearer [set]"
    assert packet["body"]["model"] == DEEPSEEK_V4_FLASH
    assert packet["body"]["response_format"] == {"type": "json_object"}
    assert packet["body"]["stream"] is False
    assert packet["body"]["thinking"] == {"type": "disabled"}
    assert "reasoning_effort" not in packet["body"]
    assert packet["body"]["temperature"] == 0.0
    system_message = packet["body"]["messages"][0]
    user_message = packet["body"]["messages"][1]
    assert system_message["role"] == "system"
    assert "parenthesized stage directions" in system_message["content"]
    assert "not token minimization" in system_message["content"]
    assert "Do not be terse merely to save tokens" in system_message["content"]
    assert user_message["role"] == "user"
    assert isinstance(user_message["content"], dict)
    assert user_message["content"]["chars"] == len(request.prompt)
    assert secret not in encoded
    assert request.prompt not in encoded


def test_phase5_provider_response_read_has_wall_clock_deadline():
    class SlowStreamingResponse:
        def read(self, size=-1):
            time.sleep(0.2)
            return b"x"

    started = time.monotonic()

    try:
        _read_response_text_with_deadline(SlowStreamingResponse(), 1, provider_name="deepseek")
    except TimeoutError as exc:
        elapsed = time.monotonic() - started
        assert "deepseek response read exceeded 1s" in str(exc)
        assert elapsed < 2.5
    else:
        raise AssertionError("expected response read timeout")


def test_phase5_provider_response_read_wraps_timed_out_object_oserror():
    class TimedOutResponse:
        def read(self, size=-1):
            raise OSError("cannot read from timed out object")

    try:
        _read_response_text_with_deadline(TimedOutResponse(), 30, provider_name="deepseek")
    except TimeoutError as exc:
        assert "deepseek response read exceeded 30s" in str(exc)
    else:
        raise AssertionError("expected response read timeout")


def test_phase5_cli_providers_reports_flash_balanced_defaults():
    payload = cli._providers_payload()
    deepseek = next(item for item in payload if item["name"] == "deepseek")

    assert deepseek["profiles"]["balanced"]["chat.route"] == DEEPSEEK_V4_FLASH
    assert deepseek["profiles"]["balanced"]["planner.propose"] == DEEPSEEK_V4_FLASH
    assert deepseek["profiles"]["quality"]["planner.propose"] == DEEPSEEK_V4_PRO
    assert deepseek["thinking"]["default"] == "disabled"
    assert deepseek["reasoning_effort"]["default"] == "medium"


def test_phase5_cli_model_packet_prints_routed_deepseek_request_without_live_gate(tmp_path: Path, capsys, monkeypatch):
    monkeypatch.delenv("HOLO_V3_LIVE_MODEL", raising=False)
    secret = "cli-packet-secret"
    monkeypatch.setenv("DEEPSEEK_API_KEY", secret)

    status = cli.main(
        [
            "--journal",
            str(tmp_path / "journal.jsonl"),
            "--index",
            str(tmp_path / "journal.sqlite"),
            "model-packet",
            "--provider",
            "deepseek",
            "--task-type",
            "planner.propose",
            "--goal",
            "搜索一下今天的热点新闻",
            "--profile",
            "balanced",
            "--thinking",
            "enabled",
            "--reasoning-effort",
            "medium",
            "--max-output-tokens",
            "provider",
            "--temperature",
            "0.2",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    encoded = json.dumps(payload, ensure_ascii=False)
    assert status == 0
    assert payload["network_call"] is False
    assert payload["route"]["parameters"]["thinking"] == "enabled"
    assert payload["route"]["parameters"]["reasoning_effort"] == "medium"
    assert payload["packet"]["body"]["response_format"] == {"type": "json_object"}
    assert payload["packet"]["body"]["thinking"] == {"type": "enabled"}
    assert payload["packet"]["body"]["reasoning_effort"] == "medium"
    assert "max_tokens" not in payload["packet"]["body"]
    assert payload["packet"]["body"]["temperature"] == 0.2
    assert secret not in encoded


def test_phase5_cli_model_packet_honors_explicit_model_override(tmp_path: Path, capsys, monkeypatch):
    monkeypatch.delenv("HOLO_V3_LIVE_MODEL", raising=False)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "cli-model-override-secret")

    status = cli.main(
        [
            "--journal",
            str(tmp_path / "journal.jsonl"),
            "--index",
            str(tmp_path / "journal.sqlite"),
            "model-packet",
            "--provider",
            "deepseek",
            "--task-type",
            "planner.propose",
            "--goal",
            "分析一个复杂任务",
            "--profile",
            "balanced",
            "--model",
            DEEPSEEK_V4_PRO,
            "--latency-target",
            "fast",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert status == 0
    assert payload["route"]["parameters"]["model_locked"] is True
    assert payload["packet"]["body"]["model"] == DEEPSEEK_V4_PRO
    assert payload["route"]["parameters"]["generation_policy"]["model_locked"] is True


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
        self.prompts = []

    def run(self, request):
        self.last_prompt = request.prompt
        self.prompts.append(request.prompt)
        return super().run(request)


class MalformedThenJsonProvider:
    name = "fake_repair"
    model = "fake-repair"

    def __init__(self, repaired_response):
        self.repaired_response = dict(repaired_response)
        self.prompts = []
        self.calls = 0

    def run(self, request):
        self.prompts.append(request.prompt)
        self.calls += 1
        if self.calls == 1:
            text = '{"answer": "unterminated'
        else:
            text = json.dumps(self.repaired_response, ensure_ascii=False, sort_keys=True)
        return ProcessorResult(
            result_id=f"result-{request.request_id}",
            request_id=request.request_id,
            status="ok",
            output={"text": text, "provider": self.name, "model": self.model},
            usage={"prompt_tokens": len(request.prompt), "completion_tokens": len(text), "total_tokens": len(request.prompt) + len(text)},
            error=None,
        )


class AlwaysMalformedAnswerProvider:
    name = "fake_salvage"
    model = "fake-salvage"

    def __init__(self, text):
        self.text = str(text)
        self.prompts = []

    def run(self, request):
        self.prompts.append(request.prompt)
        return ProcessorResult(
            result_id=f"result-{request.request_id}",
            request_id=request.request_id,
            status="ok",
            output={"text": self.text, "provider": self.name, "model": self.model},
            usage={
                "prompt_tokens": len(request.prompt),
                "completion_tokens": len(self.text),
                "total_tokens": len(request.prompt) + len(self.text),
            },
            error=None,
        )
