from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Literal

from kernel_v3.contracts import JsonObject
from kernel_v3.processors.contracts import (
    EVALUATOR_PROMPT_CONTRACT,
    EVALUATOR_SCHEMA,
    PLANNER_PROMPT_CONTRACT,
    PLANNER_SCHEMA,
    SYNTHESIZER_PROMPT_CONTRACT,
    SYNTHESIZER_SCHEMA,
    JsonSchema,
)
from kernel_v3.processors.fabric import ProcessorFabric


ScenarioExpectation = Literal[
    "planner_retrieval_tool",
    "planner_ask_user",
    "evaluator_final_answer_ready",
    "evaluator_continue",
    "synthesizer_cites_known_refs",
]


@dataclass(frozen=True, kw_only=True)
class SemanticScenario:
    scenario_id: str
    task_type: str
    schema: JsonSchema
    prompt: str
    expectation: ScenarioExpectation
    max_tokens: int = 512
    tags: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True, kw_only=True)
class SemanticScenarioResult:
    scenario_id: str
    task_type: str
    status: str
    provider: str
    model: str
    duration_ms: int
    errors: list[str]
    parsed: JsonObject | None
    usage: JsonObject

    def to_dict(self) -> JsonObject:
        return {
            "scenario_id": self.scenario_id,
            "task_type": self.task_type,
            "status": self.status,
            "provider": self.provider,
            "model": self.model,
            "duration_ms": self.duration_ms,
            "errors": list(self.errors),
            "parsed": self.parsed,
            "usage": dict(self.usage),
        }


def deepseek_v4_semantic_scenarios() -> list[SemanticScenario]:
    return [
        SemanticScenario(
            scenario_id="planner_retrieval_tool_zh",
            task_type="planner.propose",
            schema=PLANNER_SCHEMA,
            prompt=_prompt(
                contract=PLANNER_PROMPT_CONTRACT,
                role="planner",
                dialogue=[
                    {
                        "role": "user",
                        "content": "请用最新证据回答 DeepSeek V4 API 现在有哪些模型。当前上下文没有外部证据。",
                    }
                ],
                context={
                    "available_tools": [
                        {
                            "name": "retrieval.run",
                            "side_effect_class": "read",
                            "payload_contract": {"goal": "string", "query": "string"},
                        },
                        {"name": "respond", "side_effect_class": "none"},
                        {"name": "ask_user", "side_effect_class": "none"},
                    ],
                    "host_rules": [
                        "The model only proposes an action; the host validates and executes.",
                        "When current evidence is missing for a current factual question, propose retrieval.run.",
                        "Do not answer directly before retrieval.",
                    ],
                },
                required_output={
                    "action_id": "act-live-retrieval",
                    "kind": "tool",
                    "name": "retrieval.run",
                    "description": "Run retrieval for current DeepSeek V4 model evidence.",
                    "payload": {"goal": "DeepSeek V4 API models", "query": "DeepSeek V4 API models"},
                    "score": 0.9,
                    "reasons": ["current external evidence is required"],
                    "side_effect_class": "read",
                },
            ),
            expectation="planner_retrieval_tool",
            tags=("planner", "zh", "retrieval"),
        ),
        SemanticScenario(
            scenario_id="planner_ask_user_missing_target_zh",
            task_type="planner.propose",
            schema=PLANNER_SCHEMA,
            prompt=_prompt(
                contract=PLANNER_PROMPT_CONTRACT,
                role="planner",
                dialogue=[
                    {"role": "user", "content": "帮我把那个文件整理成摘要，越快越好。"},
                ],
                context={
                    "available_tools": [
                        {"name": "file.read", "side_effect_class": "read"},
                        {"name": "respond", "side_effect_class": "none"},
                        {"name": "ask_user", "side_effect_class": "none"},
                    ],
                    "known_files": [],
                    "host_rules": [
                        "If a required file/path is missing, ask the user for the missing target.",
                        "Do not guess a path.",
                    ],
                },
                required_output={
                    "action_id": "act-live-clarify",
                    "kind": "ask_user",
                    "name": None,
                    "description": "Ask which file should be summarized.",
                    "payload": {"question": "请提供要摘要的文件路径或文件名。"},
                    "score": 0.9,
                    "reasons": ["the file target is ambiguous"],
                    "side_effect_class": "none",
                },
            ),
            expectation="planner_ask_user",
            tags=("planner", "zh", "clarification"),
        ),
        SemanticScenario(
            scenario_id="evaluator_final_with_evidence_en",
            task_type="evaluator.assess",
            schema=EVALUATOR_SCHEMA,
            prompt=_prompt(
                contract=EVALUATOR_PROMPT_CONTRACT,
                role="evaluator",
                dialogue=[
                    {"role": "user", "content": "Which DeepSeek V4 API model ids are available?"},
                    {
                        "role": "host_observation",
                        "content": {
                            "retrieval_report": {
                                "status": "sufficient",
                                "evidence_ids": ["ev-v4-models"],
                                "citation_ids": ["cite-v4-models"],
                                "preview": "The API lists deepseek-v4-flash and deepseek-v4-pro.",
                            },
                            "evidence": [
                                {
                                    "evidence_id": "ev-v4-models",
                                    "text": "DeepSeek API models include deepseek-v4-flash and deepseek-v4-pro.",
                                }
                            ],
                        },
                    },
                ],
                context={
                    "host_rules": [
                        "Return final_answer_ready only when evidence is enough.",
                        "If evidence is enough, missing_evidence must be empty.",
                    ]
                },
                required_output={
                    "status": "final_answer_ready",
                    "answer": "DeepSeek V4 API exposes deepseek-v4-flash and deepseek-v4-pro.",
                    "stop_reason": "completed",
                    "missing_evidence": [],
                },
            ),
            expectation="evaluator_final_answer_ready",
            tags=("evaluator", "evidence"),
        ),
        SemanticScenario(
            scenario_id="evaluator_continue_missing_citation_en",
            task_type="evaluator.assess",
            schema=EVALUATOR_SCHEMA,
            prompt=_prompt(
                contract=EVALUATOR_PROMPT_CONTRACT,
                role="evaluator",
                dialogue=[
                    {"role": "user", "content": "Tell me the current DeepSeek V4 API model ids with citations."},
                    {
                        "role": "host_observation",
                        "content": {
                            "retrieval_report": {
                                "status": "insufficient_evidence",
                                "evidence_ids": [],
                                "citation_ids": [],
                                "preview": "",
                            },
                            "diagnostics": {"reason": "no citations"},
                        },
                    },
                ],
                context={
                    "host_rules": [
                        "If citations are required but missing, continue retrieval.",
                        "Do not mark final_answer_ready without citations.",
                    ]
                },
                required_output={
                    "status": "continue",
                    "answer": None,
                    "stop_reason": None,
                    "missing_evidence": ["cited source for current DeepSeek V4 API model ids"],
                },
            ),
            expectation="evaluator_continue",
            tags=("evaluator", "missing_evidence"),
        ),
        SemanticScenario(
            scenario_id="synthesizer_known_citations_zh",
            task_type="synthesizer.answer",
            schema=SYNTHESIZER_SCHEMA,
            prompt=_prompt(
                contract=SYNTHESIZER_PROMPT_CONTRACT,
                role="synthesizer",
                dialogue=[
                    {"role": "user", "content": "请回答 DeepSeek V4 API 的模型 ID，并只引用给定 citation。"},
                ],
                context={
                    "retrieval_report": {
                        "status": "sufficient",
                        "evidence_ids": ["ev-v4-models"],
                        "citation_ids": ["cite-v4-models"],
                    },
                    "evidence": [
                        {
                            "evidence_id": "ev-v4-models",
                            "text": "DeepSeek V4 API supports deepseek-v4-flash and deepseek-v4-pro.",
                        }
                    ],
                    "citations": [
                        {
                            "citation_id": "cite-v4-models",
                            "evidence_id": "ev-v4-models",
                            "quote": "deepseek-v4-flash and deepseek-v4-pro",
                        }
                    ],
                    "host_rules": [
                        "Use only the provided citation ids.",
                        "Do not invent citation_refs.",
                    ],
                },
                required_output={
                    "answer": "DeepSeek V4 API 的模型 ID 是 deepseek-v4-flash 和 deepseek-v4-pro。",
                    "citation_refs": ["cite-v4-models"],
                    "confidence": 0.9,
                    "limitations": [],
                    "used_evidence": ["ev-v4-models"],
                },
            ),
            expectation="synthesizer_cites_known_refs",
            tags=("synthesizer", "zh", "citations"),
        ),
    ]


def run_semantic_scenarios(
    fabric: ProcessorFabric,
    *,
    task_id: str,
    run_id: str,
    context_id: str,
    scenarios: list[SemanticScenario] | None = None,
    provider: str | None = None,
    model: str | None = None,
) -> list[SemanticScenarioResult]:
    results: list[SemanticScenarioResult] = []
    for index, scenario in enumerate(scenarios or deepseek_v4_semantic_scenarios(), start=1):
        outcome = fabric.run_json(
            task_type=scenario.task_type,
            task_id=task_id,
            run_id=run_id,
            context_id=context_id,
            step_id=f"semantic-scenario-{index}",
            prompt=scenario.prompt,
            schema=scenario.schema,
            provider=provider,
            model=model,
            parameters={"scenario_id": scenario.scenario_id, "max_tokens": scenario.max_tokens},
        )
        errors = list(validate_semantic_scenario(scenario, outcome.parsed))
        if outcome.result.status != "ok":
            errors.append(outcome.result.error or "processor_failed")
        results.append(
            SemanticScenarioResult(
                scenario_id=scenario.scenario_id,
                task_type=scenario.task_type,
                status="ok" if not errors else "failed",
                provider=outcome.provider,
                model=outcome.model,
                duration_ms=outcome.duration_ms,
                errors=errors,
                parsed=outcome.parsed,
                usage=dict(outcome.result.usage),
            )
        )
    return results


def validate_semantic_scenario(scenario: SemanticScenario, parsed: JsonObject | None) -> list[str]:
    if parsed is None:
        return ["missing_parsed_output"]
    expectation = scenario.expectation
    errors: list[str] = []
    if expectation == "planner_retrieval_tool":
        _expect(parsed.get("kind") == "tool", "expected_tool_action", errors)
        _expect(parsed.get("name") == "retrieval.run", "expected_retrieval_run", errors)
        _expect(isinstance(parsed.get("payload"), dict) and bool(parsed["payload"]), "expected_payload", errors)
        _expect(parsed.get("side_effect_class") in {"read", "network"}, "expected_read_or_network_side_effect", errors)
    elif expectation == "planner_ask_user":
        _expect(parsed.get("kind") == "ask_user", "expected_ask_user", errors)
        payload = parsed.get("payload")
        _expect(isinstance(payload, dict) and bool(payload.get("question")), "expected_question_payload", errors)
        _expect(parsed.get("side_effect_class") == "none", "expected_no_side_effect", errors)
    elif expectation == "evaluator_final_answer_ready":
        _expect(parsed.get("status") == "final_answer_ready", "expected_final_answer_ready", errors)
        _expect(parsed.get("missing_evidence") == [], "expected_no_missing_evidence", errors)
        _expect(isinstance(parsed.get("answer"), str) and bool(parsed.get("answer")), "expected_answer", errors)
    elif expectation == "evaluator_continue":
        _expect(parsed.get("status") == "continue", "expected_continue", errors)
        missing = parsed.get("missing_evidence")
        _expect(isinstance(missing, list) and bool(missing), "expected_missing_evidence", errors)
    elif expectation == "synthesizer_cites_known_refs":
        _expect("cite-v4-models" in _string_list(parsed.get("citation_refs")), "expected_known_citation", errors)
        _expect("ev-v4-models" in _string_list(parsed.get("used_evidence")), "expected_known_evidence", errors)
        _expect(isinstance(parsed.get("answer"), str) and bool(parsed.get("answer")), "expected_answer", errors)
        unknown_citations = set(_string_list(parsed.get("citation_refs"))) - {"cite-v4-models"}
        _expect(not unknown_citations, "unexpected_citation_refs:" + ",".join(sorted(unknown_citations)), errors)
    else:
        errors.append(f"unknown_expectation:{expectation}")
    return errors


def scenario_report_payload(results: list[SemanticScenarioResult]) -> JsonObject:
    return {
        "status": "ok" if all(result.status == "ok" for result in results) else "failed",
        "scenario_count": len(results),
        "passed": sum(1 for result in results if result.status == "ok"),
        "failed": [result.scenario_id for result in results if result.status != "ok"],
        "results": [result.to_dict() for result in results],
    }


def _prompt(
    *,
    contract: str,
    role: str,
    dialogue: list[JsonObject],
    context: JsonObject,
    required_output: JsonObject,
) -> str:
    return json.dumps(
        {
            "contract": contract,
            "role": role,
            "dialogue": dialogue,
            "context": context,
            "instruction": [
                "Return exactly one JSON object.",
                "The JSON must match the contract and required_output shape.",
                "Do not include markdown, commentary, or additional keys unless needed by the contract.",
            ],
            "required_output": required_output,
        },
        ensure_ascii=False,
        sort_keys=True,
    )


def _expect(condition: bool, error: str, errors: list[str]) -> None:
    if not condition:
        errors.append(error)


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]
