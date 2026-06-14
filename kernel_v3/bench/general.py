from __future__ import annotations

import json
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from kernel_v3.agent.answer_profile import infer_answer_profile
from kernel_v3.agent.contracts import SemanticIntake
from kernel_v3.agent.taskgraph import build_task_execution_plan, task_graph_from_semantic, validate_task_graph
from kernel_v3.chat.contracts import ChatRuntimeResult
from kernel_v3.contracts import Contract, JsonObject
from kernel_v3.journal import JournalStore


GENERAL_CAPABILITY_GAUNTLET_SCHEMA = "holo.kernel_v3.general_capability_gauntlet.v1"


@dataclass(frozen=True, kw_only=True)
class GeneralCapabilityCase(Contract):
    case_id: str
    category: str
    prompt: str
    semantic_intake: JsonObject
    expected_mode: str
    expected_tools: list[str] = field(default_factory=list)
    forbidden_tools: list[str] = field(default_factory=list)
    expected_domains: list[str] = field(default_factory=list)
    metadata: JsonObject = field(default_factory=dict)


@dataclass(frozen=True, kw_only=True)
class GeneralCapabilityResult(Contract):
    case_id: str
    category: str
    status: str
    prompt: str
    expected_mode: str
    selected_mode: str
    expected_tools: list[str]
    observed_tools: list[str]
    missing_tools: list[str]
    forbidden_tools_seen: list[str]
    expected_domains: list[str]
    observed_domains: list[str]
    score: float
    checks: JsonObject
    task_id: str | None = None
    run_id: str | None = None
    answer_present: bool = False
    final_answer_present: bool = False
    usage: JsonObject = field(default_factory=dict)
    metadata: JsonObject = field(default_factory=dict)


class ChatRuntimeLike(Protocol):
    journal: JournalStore

    def receive(self, text: str, *, thread_id: str = "default") -> ChatRuntimeResult: ...


def default_general_capability_cases() -> list[GeneralCapabilityCase]:
    return [
        _case(
            case_id="general-direct-chat",
            category="direct_chat",
            prompt="Hi. Answer briefly and naturally.",
            primary_intent="smalltalk",
            suggested_mode="semantic_answer",
            intents=[
                _intent(
                    kind="smalltalk",
                    text="Answer a harmless greeting without tools.",
                    capabilities=["communication.draft"],
                    metadata={"domain": "conversation", "activity": "respond"},
                )
            ],
            expected_mode="semantic_answer",
            forbidden_tools=["retrieval.run", "workspace.search", "calculator.compute", "system.time"],
            expected_domains=["conversation"],
        ),
        _case(
            case_id="general-roleplay-writing",
            category="roleplay_writing",
            prompt="Roleplay as a calm project lead and draft a short status update.",
            primary_intent="roleplay_status_writing",
            suggested_mode="semantic_answer",
            intents=[
                _intent(
                    kind="roleplay",
                    text="Adopt a calm project lead voice.",
                    capabilities=["roleplay.perform", "communication.draft"],
                    metadata={"domain": "communication", "activity": "draft"},
                )
            ],
            expected_mode="semantic_answer",
            forbidden_tools=["retrieval.run", "workspace.search"],
            expected_domains=["communication"],
        ),
        _case(
            case_id="general-technical-docs-research",
            category="technical_research",
            prompt="Find the official API authentication pattern for a developer tool.",
            primary_intent="technical_documentation_research",
            suggested_mode="retrieval_answer",
            intents=[
                _intent(
                    kind="technical_documentation_research",
                    text="Research official API authentication documentation.",
                    capabilities=["technical.api_documentation"],
                    metadata={"domain": "technical", "activity": "research"},
                )
            ],
            expected_mode="retrieval_answer",
            expected_tools=["retrieval.run"],
            expected_domains=["technical"],
        ),
        _case(
            case_id="general-academic-frontier",
            category="academic_research",
            prompt="Survey recent approaches for a hard physics or math research question.",
            primary_intent="academic_frontier_research",
            suggested_mode="retrieval_answer",
            intents=[
                _intent(
                    kind="academic_frontier_research",
                    text="Research recent scholarly work and open problems.",
                    capabilities=["academic.frontier_research"],
                    metadata={"domain": "academic", "activity": "research"},
                )
            ],
            expected_mode="retrieval_answer",
            expected_tools=["retrieval.run"],
            expected_domains=["academic"],
        ),
        _case(
            case_id="general-workspace-read",
            category="workspace_read",
            prompt="Inspect the local project docs and summarize the relevant section.",
            primary_intent="workspace_read",
            suggested_mode="workspace_answer",
            intents=[
                _intent(
                    kind="workspace_read",
                    text="Search and read local project files.",
                    capabilities=["workspace.search", "file.read"],
                    metadata={"domain": "workspace", "activity": "read"},
                )
            ],
            expected_mode="workspace_answer",
            expected_tools=["workspace.search,file.read"],
            expected_domains=["workspace"],
        ),
        _case(
            case_id="general-memory-recall",
            category="memory",
            prompt="Recall the current project constraints before answering.",
            primary_intent="memory_grounded_answer",
            suggested_mode="semantic_answer",
            intents=[
                _intent(
                    kind="memory_recall",
                    text="Recall durable project memory before answering.",
                    capabilities=["durable_memory.search"],
                    metadata={"domain": "memory", "activity": "recall"},
                )
            ],
            expected_mode="semantic_answer",
            expected_tools=["memory.recall"],
            expected_domains=["memory"],
        ),
        _case(
            case_id="general-system-time",
            category="system",
            prompt="What is the current local date and time?",
            primary_intent="system_time",
            suggested_mode="system_answer",
            intents=[
                _intent(
                    kind="system_time",
                    text="Read current host time.",
                    capabilities=["system.time"],
                    metadata={"domain": "system", "activity": "time"},
                )
            ],
            expected_mode="system_answer",
            expected_tools=["system.time"],
            expected_domains=["system"],
        ),
        _case(
            case_id="general-math-compute",
            category="math_compute",
            prompt="Compute a numeric ratio and explain the formula.",
            primary_intent="math_compute",
            suggested_mode="semantic_answer",
            intents=[
                _intent(
                    kind="math_compute",
                    text="Use deterministic calculation for a numeric subproblem.",
                    capabilities=["calculator.compute"],
                    metadata={"domain": "math", "activity": "calculate"},
                )
            ],
            expected_mode="direct_answer",
            expected_tools=["calculator.compute"],
            expected_domains=["math"],
        ),
        _case(
            case_id="general-resident-reminder",
            category="resident",
            prompt="Remind me to review the benchmark report later.",
            primary_intent="calendar_or_reminder",
            suggested_mode="semantic_answer",
            intents=[
                _intent(
                    kind="calendar_or_reminder",
                    text="Represent a resident reminder task for scheduler handling.",
                    capabilities=["resident.reminder"],
                    metadata={"domain": "resident", "activity": "schedule", "suggested_mode": "semantic_answer"},
                )
            ],
            expected_mode="direct_answer",
            forbidden_tools=["retrieval.run", "workspace.search"],
            expected_domains=["resident"],
            metadata={"expected_boundary": "resident.reminder is host-cataloged but not a direct semantic tool"},
        ),
    ]


def run_general_capability_gauntlet(
    *,
    cases: list[GeneralCapabilityCase] | None = None,
    runtime: ChatRuntimeLike | None = None,
    thread_prefix: str = "general-gauntlet",
) -> JsonObject:
    started = int(time.time() * 1000)
    selected_cases = list(cases or default_general_capability_cases())
    results: list[GeneralCapabilityResult] = []
    for index, case in enumerate(selected_cases, start=1):
        live_result = None
        if runtime is not None:
            live_result = runtime.receive(case.prompt, thread_id=f"{thread_prefix}-{index:03d}-{case.case_id}")
        results.append(evaluate_general_capability_case(case, live_result=live_result, journal=getattr(runtime, "journal", None)))
    summary = summarize_general_capability_results(results, started_at_ms=started)
    return {
        "schema": GENERAL_CAPABILITY_GAUNTLET_SCHEMA,
        "status": "passed" if summary["failed_count"] == 0 else "failed",
        "summary": summary,
        "cases": [result.to_dict() for result in results],
    }


def evaluate_general_capability_case(
    case: GeneralCapabilityCase,
    *,
    live_result: ChatRuntimeResult | None = None,
    journal: JournalStore | None = None,
) -> GeneralCapabilityResult:
    intake = SemanticIntake.from_dict(dict(case.semantic_intake))
    proposal = task_graph_from_semantic(intake)
    validation = validate_task_graph(proposal)
    plan = build_task_execution_plan(proposal, validation)
    profile = infer_answer_profile(case.prompt, semantic_intake=intake, task_plan=plan)
    observed_tools = _observed_tools(plan.to_dict())
    observed_domains = _observed_domains(plan.to_dict(), profile.to_dict())
    missing_tools = [tool for tool in case.expected_tools if tool not in observed_tools]
    forbidden_seen = [tool for tool in case.forbidden_tools if tool in observed_tools]
    missing_domains = [domain for domain in case.expected_domains if domain not in observed_domains]
    checks: JsonObject = {
        "mode": plan.selected_mode == case.expected_mode,
        "expected_tools_present": not missing_tools,
        "forbidden_tools_absent": not forbidden_seen,
        "expected_domains_present": not missing_domains,
        "validation_ready_or_boundary": validation.status in {"ready", "blocked"},
    }
    usage = _live_usage(journal, task_id=live_result.task_id if live_result is not None else None)
    if live_result is not None:
        checks["live_answer_present"] = bool(live_result.answer or live_result.final_answer)
    score = _score_checks(checks)
    return GeneralCapabilityResult(
        case_id=case.case_id,
        category=case.category,
        status="passed" if score >= 1.0 else "failed",
        prompt=case.prompt,
        expected_mode=case.expected_mode,
        selected_mode=plan.selected_mode,
        expected_tools=list(case.expected_tools),
        observed_tools=observed_tools,
        missing_tools=missing_tools,
        forbidden_tools_seen=forbidden_seen,
        expected_domains=list(case.expected_domains),
        observed_domains=observed_domains,
        score=score,
        checks=checks,
        task_id=live_result.task_id if live_result is not None else None,
        run_id=live_result.run_id if live_result is not None else None,
        answer_present=bool(live_result.answer) if live_result is not None else False,
        final_answer_present=bool(live_result.final_answer) if live_result is not None else False,
        usage=usage,
        metadata={
            "task_graph_status": validation.status,
            "task_graph_reasons": list(validation.reasons),
            "answer_profile": profile.to_dict(),
            **dict(case.metadata),
        },
    )


def summarize_general_capability_results(results: list[GeneralCapabilityResult], *, started_at_ms: int | None = None) -> JsonObject:
    total = len(results)
    passed = sum(1 for result in results if result.status == "passed")
    usage = [_json_object(result.usage) for result in results]
    cache_hit = sum(_int(item.get("prompt_cache_hit_tokens")) for item in usage)
    cache_miss = sum(_int(item.get("prompt_cache_miss_tokens")) for item in usage)
    cache_total = cache_hit + cache_miss
    return {
        "case_count": total,
        "passed_count": passed,
        "failed_count": total - passed,
        "pass_rate": round(passed / total, 6) if total else 0.0,
        "category_counts": dict(Counter(result.category for result in results)),
        "average_score": round(sum(result.score for result in results) / total, 6) if total else 0.0,
        "tool_coverage": sorted({tool for result in results for tool in result.observed_tools}),
        "mode_counts": dict(Counter(result.selected_mode for result in results)),
        "domain_coverage": sorted({domain for result in results for domain in result.observed_domains}),
        "total_tokens": sum(_int(item.get("total_tokens")) for item in usage),
        "prompt_cache_hit_tokens": cache_hit,
        "prompt_cache_miss_tokens": cache_miss,
        "prompt_cache_hit_ratio": round(cache_hit / cache_total, 6) if cache_total else None,
        "started_at_ms": started_at_ms,
        "ended_at_ms": int(time.time() * 1000),
    }


def write_general_capability_gauntlet_outputs(
    report: JsonObject,
    *,
    output_path: str | Path | None = None,
    summary_path: str | Path | None = None,
    jsonl_path: str | Path | None = None,
) -> JsonObject:
    outputs: JsonObject = {}
    if output_path is not None:
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        outputs["output"] = str(path)
    if summary_path is not None:
        path = Path(summary_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report.get("summary", {}), ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        outputs["summary_output"] = str(path)
    if jsonl_path is not None:
        path = Path(jsonl_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        lines = [json.dumps(case, ensure_ascii=False, sort_keys=True) for case in report.get("cases", []) if isinstance(case, dict)]
        path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
        outputs["jsonl_output"] = str(path)
    return outputs


def _case(
    *,
    case_id: str,
    category: str,
    prompt: str,
    primary_intent: str,
    suggested_mode: str,
    intents: list[JsonObject],
    expected_mode: str,
    expected_tools: list[str] | None = None,
    forbidden_tools: list[str] | None = None,
    expected_domains: list[str] | None = None,
    metadata: JsonObject | None = None,
) -> GeneralCapabilityCase:
    return GeneralCapabilityCase(
        case_id=case_id,
        category=category,
        prompt=prompt,
        semantic_intake={
            "intake_id": f"intake-{case_id}",
            "goal": prompt,
            "primary_intent": primary_intent,
            "suggested_mode": suggested_mode,
            "compound": len(intents) > 1,
            "requires_clarification": False,
            "intents": intents,
            "blocked_capabilities": [],
            "warnings": [],
            "response_hint": None,
            "clarification_question": None,
        },
        expected_mode=expected_mode,
        expected_tools=list(expected_tools or []),
        forbidden_tools=list(forbidden_tools or []),
        expected_domains=list(expected_domains or []),
        metadata=dict(metadata or {}),
    )


def _intent(*, kind: str, text: str, capabilities: list[str], metadata: JsonObject) -> JsonObject:
    return {
        "kind": kind,
        "text": text,
        "sequence_index": 1,
        "required_capabilities": list(capabilities),
        "risk": "normal",
        "status": "ready",
        "metadata": dict(metadata),
    }


def _observed_tools(plan: JsonObject) -> list[str]:
    tools: list[str] = []
    for step in plan.get("steps", []):
        if not isinstance(step, dict):
            continue
        tool = step.get("tool_name")
        if isinstance(tool, str) and tool:
            tools.append(tool)
    return _ordered_unique(tools)


def _observed_domains(plan: JsonObject, answer_profile: JsonObject) -> list[str]:
    domains: list[str] = []
    profile_metadata = answer_profile.get("metadata")
    if isinstance(profile_metadata, dict) and isinstance(profile_metadata.get("domain"), str):
        domains.append(str(profile_metadata["domain"]))
    for step in plan.get("steps", []):
        if not isinstance(step, dict):
            continue
        node = step.get("metadata")
        if not isinstance(node, dict):
            continue
        node_metadata = node.get("node_metadata")
        if not isinstance(node_metadata, dict):
            continue
        state = node_metadata.get("state_profile")
        if isinstance(state, dict) and isinstance(state.get("domain"), str):
            domains.append(str(state["domain"]))
        elif isinstance(node_metadata.get("domain"), str):
            domains.append(str(node_metadata["domain"]))
    return _ordered_unique([domain for domain in domains if domain])


def _live_usage(journal: JournalStore | None, *, task_id: str | None) -> JsonObject:
    if journal is None or not task_id:
        return {}
    usage: JsonObject = {}
    for record in journal.records(task_id=task_id, kind="processor_result"):
        item = record.data.get("usage")
        if not isinstance(item, dict):
            continue
        for key in ("prompt_tokens", "completion_tokens", "total_tokens", "prompt_cache_hit_tokens", "prompt_cache_miss_tokens"):
            usage[key] = _int(usage.get(key)) + _int(item.get(key))
    cache_hit = _int(usage.get("prompt_cache_hit_tokens"))
    cache_miss = _int(usage.get("prompt_cache_miss_tokens"))
    if cache_hit or cache_miss:
        usage["prompt_cache_hit_ratio"] = round(cache_hit / (cache_hit + cache_miss), 6)
    return usage


def _score_checks(checks: JsonObject) -> float:
    values = [value for value in checks.values() if isinstance(value, bool)]
    if not values:
        return 0.0
    return round(sum(1 for value in values if value) / len(values), 6)


def _json_object(value: object) -> JsonObject:
    return dict(value) if isinstance(value, dict) else {}


def _int(value: object) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _ordered_unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result
