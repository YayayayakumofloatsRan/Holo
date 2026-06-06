from __future__ import annotations

import hashlib
import json

from kernel_v3.agent.contracts import AnswerProfile, SemanticIntake, TaskExecutionPlan
from kernel_v3.contracts import JsonObject
from kernel_v3.journal_redaction import redact_journal_data
from kernel_v3.processors.fabric import ProcessorFabric
from kernel_v3.workmethod.contracts import (
    StrategyShift,
    ThreadWorkingSet,
    WorkFrame,
    WorkGapAssessment,
    WorkMethod,
    WorkMethodState,
)
from kernel_v3.workmethod.memory import build_thread_working_set
from kernel_v3.workmethod.prompts import (
    WORKMETHOD_FRAME_PROMPT_CONTRACT,
    WORKMETHOD_FRAME_SCHEMA,
    WORKMETHOD_GAP_PROMPT_CONTRACT,
    WORKMETHOD_GAP_SCHEMA,
)


class WorkMethodSupervisor:
    def __init__(self, *, processor_fabric: ProcessorFabric | None = None, mode: str = "rule") -> None:
        self.processor_fabric = processor_fabric
        self.mode = mode

    def frame_task(
        self,
        *,
        goal: str,
        thread_id: str,
        semantic_intake: SemanticIntake,
        task_plan: TaskExecutionPlan,
        answer_profile: AnswerProfile,
        execution_metadata: JsonObject | None,
        task_id: str | None = None,
        run_id: str = "workmethod-pre",
    ) -> WorkMethodState:
        fallback = _rule_workmethod_state(
            goal=goal,
            thread_id=thread_id,
            semantic_intake=semantic_intake,
            task_plan=task_plan,
            answer_profile=answer_profile,
            execution_metadata=execution_metadata,
        )
        if self.mode != "model" or self.processor_fabric is None:
            return fallback
        prompt = _frame_prompt(
            goal=goal,
            thread_id=thread_id,
            semantic_intake=semantic_intake,
            task_plan=task_plan,
            answer_profile=answer_profile,
            execution_metadata=execution_metadata,
            fallback=fallback,
        )
        outcome = self.processor_fabric.run_json(
            task_type="workmethod.frame",
            task_id=task_id,
            run_id=run_id,
            context_id=f"workmethod:{_short_hash(thread_id, goal)}",
            prompt=prompt,
            schema=WORKMETHOD_FRAME_SCHEMA,
            parameters={"adapter": "WorkMethodSupervisor"},
        )
        if outcome.parsed is None:
            diagnostics = dict(fallback.diagnostics)
            diagnostics["model_status"] = "failed"
            diagnostics["model_error"] = outcome.result.error
            return WorkMethodState(
                state_id=fallback.state_id,
                frame=fallback.frame,
                method=fallback.method,
                thread_working_set=fallback.thread_working_set,
                source="rule_fallback_after_model_failure",
                diagnostics=diagnostics,
            )
        return _state_from_model(outcome.parsed, fallback=fallback)

    def assess_gap(
        self,
        *,
        root_goal: str,
        run_delta: JsonObject,
        agent_result: JsonObject,
        mission_assessment: JsonObject | None = None,
        workmethod: JsonObject | None = None,
        task_id: str | None = None,
        run_id: str = "",
    ) -> WorkGapAssessment:
        fallback = _rule_gap_assessment(
            root_goal=root_goal,
            run_delta=run_delta,
            agent_result=agent_result,
            mission_assessment=mission_assessment,
            workmethod=workmethod,
        )
        if self.mode != "model" or self.processor_fabric is None:
            return fallback
        outcome = self.processor_fabric.run_json(
            task_type="workmethod.gap",
            task_id=task_id,
            run_id=run_id or str(agent_result.get("run_id") or "workmethod-gap"),
            context_id=f"workmethod-gap:{_short_hash(root_goal, run_id)}",
            prompt=_gap_prompt(
                root_goal=root_goal,
                run_delta=run_delta,
                agent_result=agent_result,
                mission_assessment=mission_assessment,
                workmethod=workmethod,
                fallback=fallback,
            ),
            schema=WORKMETHOD_GAP_SCHEMA,
            parameters={"adapter": "WorkMethodSupervisor"},
        )
        if outcome.parsed is None:
            return fallback
        return _gap_from_model(outcome.parsed, fallback=fallback)


def _rule_workmethod_state(
    *,
    goal: str,
    thread_id: str,
    semantic_intake: SemanticIntake,
    task_plan: TaskExecutionPlan,
    answer_profile: AnswerProfile,
    execution_metadata: JsonObject | None,
) -> WorkMethodState:
    capabilities = _plan_capabilities(task_plan)
    work_type = _work_type_from_plan(task_plan, capabilities=capabilities)
    method_name = _method_name(work_type, task_plan.selected_mode)
    frame = WorkFrame(
        frame_id="workframe-" + _short_hash(thread_id, goal, work_type),
        user_goal=goal,
        inferred_goal=semantic_intake.goal,
        work_type=work_type,
        difficulty=_difficulty(task_plan, answer_profile=answer_profile),
        risk_level=_risk_level(semantic_intake),
        expected_output={
            "format": answer_profile.format,
            "detail_level": answer_profile.detail_level,
            "target_sections": list(answer_profile.target_sections),
            "language": answer_profile.language,
        },
        done_criteria=_done_criteria(task_plan, answer_profile=answer_profile),
        tool_needs=_tool_needs(task_plan),
        memory_needs=_memory_needs(capabilities),
        assumptions=_ordered_unique([*semantic_intake.warnings, *_string_list(task_plan.warnings)])[:8],
    )
    method = WorkMethod(
        method_id="workmethod-" + _short_hash(thread_id, goal, method_name),
        method_name=method_name,
        first_moves=_first_moves(work_type, task_plan),
        evidence_strategy=_evidence_strategy(task_plan),
        failure_moves=_failure_moves(work_type),
        stop_policy=_stop_policy(task_plan, answer_profile=answer_profile),
        user_interaction_policy=[
            "Do not ask the user unless a critical target, permission, destination, or safety boundary is missing.",
            "For normal progress, continue or finalize from host observations instead of pushing work back to the user.",
        ],
        notes=["Host validates tools, policy, evidence, memory, budgets, and termination."],
    )
    metadata = dict(execution_metadata or {})
    working = build_thread_working_set(
        thread_id=thread_id,
        active_goal=goal,
        current_method=method.method_name,
        thread_context=_json_object(metadata.get("thread_rag_context")) or _json_object(metadata.get("thread_working_context")),
        mission_context=_json_object(metadata.get("mission_context")),
        interaction_preferences=_json_object(metadata.get("interaction_preferences")),
    )
    return WorkMethodState(
        state_id="workstate-" + _short_hash(thread_id, goal, method.method_name),
        frame=frame.to_dict(),
        method=method.to_dict(),
        thread_working_set=working.to_dict(),
        source="rule",
        diagnostics={"mode": task_plan.selected_mode, "capabilities": capabilities},
    )


def _rule_gap_assessment(
    *,
    root_goal: str,
    run_delta: JsonObject,
    agent_result: JsonObject,
    mission_assessment: JsonObject | None,
    workmethod: JsonObject | None,
) -> WorkGapAssessment:
    mission_assessment = dict(mission_assessment or {})
    workmethod = dict(workmethod or {})
    missing = _ordered_unique(
        [
            *_string_list(mission_assessment.get("missing_requirements")),
            *_missing_from_run_delta(run_delta),
        ]
    )[:24]
    covered = _ordered_unique(
        [
            *_string_list(run_delta.get("evidence_refs")),
            *_string_list(run_delta.get("citation_refs")),
            *([] if missing else ["agent_result_ready"]),
        ]
    )[:24]
    attempted_queries = _attempted_queries(run_delta)
    redundant = _redundant_work(run_delta)
    source_families = _suggested_source_families(run_delta, workmethod=workmethod)
    shift = None
    should_finalize = str(agent_result.get("status") or "") == "completed" and not missing
    should_shift = bool(missing) and (bool(redundant) or _retrieval_stalled(run_delta))
    if should_shift:
        shift = StrategyShift(
            shift_id="shift-" + _short_hash(root_goal, "|".join(missing), "|".join(attempted_queries[-4:])),
            shift_reason="missing_goal_coverage_after_attempts",
            next_method="materially_different_strategy",
            avoid_repeating=attempted_queries[-16:],
            new_source_families=source_families,
            new_query_moves=_query_moves_from_gaps(missing),
            new_tool_plan_hint={
                "instruction": "Use a materially different work move; do not repeat the same query/source pattern.",
                "missing": missing[:12],
                "avoid_repeating": attempted_queries[-12:],
            },
            confidence=0.78,
        )
    return WorkGapAssessment(
        assessment_id="workgap-" + _short_hash(root_goal, str(run_delta.get("run_id") or "")),
        covered=covered,
        missing=missing,
        redundant_work=redundant,
        stale_context=[],
        wrong_strategy=["retrieval_strategy_stalled"] if should_shift else [],
        should_continue=bool(missing) and not should_finalize,
        should_shift_strategy=should_shift,
        should_finalize=should_finalize,
        reason="final_ready" if should_finalize else ("strategy_shift_needed" if should_shift else "continue_or_limitations"),
        strategy_shift=shift.to_dict() if shift is not None else None,
    )


def _state_from_model(data: JsonObject, *, fallback: WorkMethodState) -> WorkMethodState:
    raw_frame = _json_object(data.get("work_frame")) or _json_object(data.get("frame"))
    raw_method = _json_object(data.get("work_method")) or _json_object(data.get("method"))
    raw_working = (
        _json_object(data.get("thread_working_set"))
        or _json_object(data.get("working_set"))
        or _json_object(data.get("thread_memory"))
    )
    diagnostics = _merge_dict(fallback.diagnostics, _json_object(data.get("diagnostics")))
    if not raw_frame or not raw_method or not raw_working:
        diagnostics["model_status"] = "shape_fallback"
        diagnostics["missing_sections"] = [
            section
            for section, value in (
                ("work_frame", raw_frame),
                ("work_method", raw_method),
                ("thread_working_set", raw_working),
            )
            if not value
        ]
        return WorkMethodState(
            state_id=fallback.state_id,
            frame=fallback.frame,
            method=fallback.method,
            thread_working_set=fallback.thread_working_set,
            source="rule_fallback_after_model_shape_error",
            diagnostics=redact_journal_data(diagnostics),
        )
    frame = _merge_dict(fallback.frame, raw_frame)
    method = _merge_dict(fallback.method, raw_method)
    working = _merge_dict(fallback.thread_working_set, raw_working)
    if "work_frame" not in data or "work_method" not in data or "thread_working_set" not in data:
        diagnostics["accepted_alias_sections"] = [
            key
            for key in ("frame", "method", "working_set", "thread_memory")
            if isinstance(data.get(key), dict)
        ]
    diagnostics["model_status"] = "ok"
    return WorkMethodState(
        state_id=str(data.get("state_id") or fallback.state_id),
        frame=redact_journal_data(frame),
        method=redact_journal_data(method),
        thread_working_set=redact_journal_data(working),
        source="model",
        diagnostics=redact_journal_data(diagnostics),
    )


def _gap_from_model(data: JsonObject, *, fallback: WorkGapAssessment) -> WorkGapAssessment:
    shift = data.get("strategy_shift")
    shift = dict(shift) if isinstance(shift, dict) else fallback.strategy_shift
    return WorkGapAssessment(
        assessment_id=str(data.get("assessment_id") or fallback.assessment_id),
        covered=_string_list(data.get("covered")) or list(fallback.covered),
        missing=_string_list(data.get("missing")) or list(fallback.missing),
        redundant_work=_string_list(data.get("redundant_work")),
        stale_context=_string_list(data.get("stale_context")),
        wrong_strategy=_string_list(data.get("wrong_strategy")),
        should_continue=bool(data.get("should_continue")),
        should_shift_strategy=bool(data.get("should_shift_strategy")),
        should_finalize=bool(data.get("should_finalize")),
        reason=str(data.get("reason") or fallback.reason),
        strategy_shift=shift,
    )


def _frame_prompt(
    *,
    goal: str,
    thread_id: str,
    semantic_intake: SemanticIntake,
    task_plan: TaskExecutionPlan,
    answer_profile: AnswerProfile,
    execution_metadata: JsonObject | None,
    fallback: WorkMethodState,
) -> str:
    payload = {
        "contract": WORKMETHOD_FRAME_PROMPT_CONTRACT,
        "goal": goal,
        "thread_id": thread_id,
        "semantic_intake": semantic_intake.to_dict(),
        "task_execution_plan": task_plan.to_dict(),
        "answer_profile": answer_profile.to_dict(),
        "execution_metadata": _compact_prompt_metadata(execution_metadata),
        "host_fallback": fallback.to_dict(),
    }
    return json.dumps(redact_journal_data(payload), ensure_ascii=False, sort_keys=True)


def _gap_prompt(
    *,
    root_goal: str,
    run_delta: JsonObject,
    agent_result: JsonObject,
    mission_assessment: JsonObject | None,
    workmethod: JsonObject | None,
    fallback: WorkGapAssessment,
) -> str:
    payload = {
        "contract": WORKMETHOD_GAP_PROMPT_CONTRACT,
        "root_goal": root_goal,
        "workmethod": workmethod or {},
        "run_delta": run_delta,
        "agent_result": agent_result,
        "mission_assessment": mission_assessment or {},
        "host_fallback": fallback.to_dict(),
    }
    return json.dumps(redact_journal_data(payload), ensure_ascii=False, sort_keys=True)


def _work_type_from_plan(task_plan: TaskExecutionPlan, *, capabilities: list[str]) -> str:
    if task_plan.selected_mode == "retrieval_answer":
        return "research"
    if task_plan.selected_mode == "workspace_write":
        return "build_or_write"
    if task_plan.selected_mode == "workspace_answer":
        return "workspace_inspection"
    if task_plan.selected_mode == "system_answer":
        return "system_state"
    if task_plan.selected_mode == "clarify_first":
        return "clarification"
    if any(cap.startswith("memory.") or cap.startswith("durable_memory.") for cap in capabilities):
        return "memory_recall"
    return "semantic_response"


def _method_name(work_type: str, mode: str) -> str:
    if work_type == "research":
        return "goal_directed_research"
    if work_type == "build_or_write":
        return "inspect_then_write_artifact"
    if work_type == "workspace_inspection":
        return "local_evidence_inspection"
    if work_type == "clarification":
        return "ask_minimal_missing_scope"
    return f"{mode}_human_workflow"


def _difficulty(task_plan: TaskExecutionPlan, *, answer_profile: AnswerProfile) -> str:
    if answer_profile.detail_level in {"deep", "detailed"} or len(task_plan.steps) >= 3:
        return "high"
    if task_plan.selected_mode in {"retrieval_answer", "workspace_write"}:
        return "medium"
    return "low"


def _risk_level(semantic_intake: SemanticIntake) -> str:
    risks = []
    for item in semantic_intake.intents:
        if isinstance(item, dict) and isinstance(item.get("risk"), str):
            risks.append(str(item["risk"]).lower())
    if any(risk in {"high", "sensitive", "dangerous"} for risk in risks):
        return "high"
    if any(risk in {"medium", "needs_review"} for risk in risks):
        return "medium"
    return "low"


def _done_criteria(task_plan: TaskExecutionPlan, *, answer_profile: AnswerProfile) -> list[str]:
    criteria = [
        *[str(item) for item in answer_profile.minimum_coverage if item],
        *[str(section) for section in answer_profile.target_sections if section],
    ]
    if task_plan.selected_mode == "retrieval_answer":
        criteria.extend(["source-backed evidence collected", "limitations disclosed"])
    if task_plan.selected_mode == "workspace_write":
        criteria.append("requested artifact written and observed by host")
    return _ordered_unique(criteria or ["user goal answered"])


def _tool_needs(task_plan: TaskExecutionPlan) -> list[str]:
    tools: list[str] = []
    for step in task_plan.steps:
        if isinstance(step, dict) and isinstance(step.get("tool_name"), str) and step.get("tool_name"):
            tools.append(str(step["tool_name"]))
    return _ordered_unique(tools)


def _memory_needs(capabilities: list[str]) -> list[str]:
    return [
        cap
        for cap in capabilities
        if cap.startswith("memory.") or cap.startswith("durable_memory.")
    ]


def _first_moves(work_type: str, task_plan: TaskExecutionPlan) -> list[str]:
    if work_type == "research":
        return [
            "Frame the answer requirements and evidence criteria.",
            "Choose source families from the task semantics.",
            "Run one bounded evidence-gathering action, then reassess gaps.",
        ]
    if work_type == "workspace_inspection":
        return ["Locate the requested workspace evidence.", "Read or list only what the host allows.", "Answer from observed local evidence."]
    if work_type == "build_or_write":
        return ["Inspect any required local context.", "Prepare the complete artifact body.", "Write through host-validated workspace tools."]
    if work_type == "clarification":
        return ["Ask only the minimum missing scope needed to proceed."]
    return ["Answer directly from available context unless a host-visible gap requires a tool."]


def _evidence_strategy(task_plan: TaskExecutionPlan) -> list[str]:
    if task_plan.selected_mode == "retrieval_answer":
        return [
            "Prefer high-authority sources appropriate to the user goal.",
            "Treat failed or weak sources as observations for strategy shift.",
            "Use citations/evidence refs for factual final claims.",
        ]
    if task_plan.selected_mode.startswith("workspace"):
        return ["Use host observations from workspace tools as the evidence boundary."]
    return ["Use provided thread/context/memory observations; do not invent missing facts."]


def _failure_moves(work_type: str) -> list[str]:
    if work_type == "research":
        return [
            "Change source family or query intent rather than repeating similar searches.",
            "Broaden, narrow, translate, or follow references depending on the observed gap.",
            "Finalize with limitations when the main objective is sufficiently covered.",
        ]
    return ["Treat failure as an observation.", "Choose a materially different safe move or surface the limitation."]


def _stop_policy(task_plan: TaskExecutionPlan, *, answer_profile: AnswerProfile) -> list[str]:
    policy = ["Stop when done_criteria are covered or remaining gaps can be stated as limitations."]
    if task_plan.selected_mode == "retrieval_answer":
        policy.append("Do not loop only to satisfy cosmetic breadth; require material evidence progress.")
    if answer_profile.format in {"detailed_report", "deep_report", "memo"}:
        policy.append("Final answer must respect the requested output shape.")
    return policy


def _plan_capabilities(task_plan: TaskExecutionPlan) -> list[str]:
    capabilities: list[str] = []
    for step in task_plan.steps:
        if isinstance(step, dict):
            capabilities.extend(_string_list(step.get("required_capabilities")))
    return _ordered_unique(capabilities)


def _missing_from_run_delta(run_delta: JsonObject) -> list[str]:
    missing: list[str] = []
    for feedback in run_delta.get("feedback", []) if isinstance(run_delta.get("feedback"), list) else []:
        if isinstance(feedback, dict):
            missing.extend(_string_list(feedback.get("missing_evidence")))
    for failure in run_delta.get("failure_reports", []) if isinstance(run_delta.get("failure_reports"), list) else []:
        if isinstance(failure, dict):
            missing.extend(_string_list(failure.get("missing_evidence")))
            reason = failure.get("reason")
            if isinstance(reason, str) and reason:
                missing.append(reason)
    return _ordered_unique(missing)


def _attempted_queries(run_delta: JsonObject) -> list[str]:
    queries: list[str] = []
    for report in run_delta.get("retrieval_reports", []) if isinstance(run_delta.get("retrieval_reports"), list) else []:
        if not isinstance(report, dict):
            continue
        queries.extend(_string_list(report.get("attempted_queries")))
        goal_query = report.get("goal_query")
        if isinstance(goal_query, str) and goal_query:
            queries.append(goal_query)
    return _ordered_unique(queries)


def _redundant_work(run_delta: JsonObject) -> list[str]:
    queries = _attempted_queries(run_delta)
    signatures = [_query_signature(query) for query in queries]
    repeated = len(signatures) != len(set(signatures))
    reports = [
        item
        for item in run_delta.get("retrieval_reports", [])
        if isinstance(item, dict)
    ]
    all_insufficient = bool(reports) and all(item.get("status") != "sufficient" for item in reports)
    if repeated:
        return ["repeated_query_signature"]
    if len(reports) >= 2 and all_insufficient:
        return ["multiple_insufficient_retrieval_reports"]
    return []


def _retrieval_stalled(run_delta: JsonObject) -> bool:
    reports = [item for item in run_delta.get("retrieval_reports", []) if isinstance(item, dict)]
    if not reports:
        return False
    return not _string_list(run_delta.get("evidence_refs")) and not _string_list(run_delta.get("citation_refs"))


def _suggested_source_families(run_delta: JsonObject, *, workmethod: JsonObject) -> list[str]:
    method = workmethod.get("method") if isinstance(workmethod.get("method"), dict) else {}
    evidence_strategy = _string_list(method.get("evidence_strategy"))
    if any("citation" in item.lower() or "source" in item.lower() for item in evidence_strategy):
        return ["primary_or_high_authority", "domain_specific_index", "reference_chain"]
    if run_delta.get("retrieval_reports"):
        return ["alternative_authority_source", "source_directory", "scholarly_or_official_index"]
    return []


def _query_moves_from_gaps(missing: list[str]) -> list[str]:
    return _ordered_unique(
        [
            "restate the missing requirement as a search intent",
            "switch source family",
            "change granularity",
            "try local-language and English variants",
            "follow references or official indices",
            *[item.replace("_", " ").replace(":", " ") for item in missing[:4]],
        ]
    )[:12]


def _compact_prompt_metadata(value: JsonObject | None) -> JsonObject:
    if not isinstance(value, dict):
        return {}
    result: JsonObject = {}
    for key in (
        "interaction_preferences",
        "thread_working_context",
        "thread_rag_context",
        "mission_context",
        "semantic_goal",
        "host_situation",
    ):
        item = value.get(key)
        if isinstance(item, dict):
            result[key] = item
    return result


def _json_object(value: object) -> JsonObject:
    return dict(value) if isinstance(value, dict) else {}


def _merge_dict(base: JsonObject, override: JsonObject) -> JsonObject:
    result = dict(base)
    result.update({key: value for key, value in override.items() if value not in (None, "", [], {})})
    return result


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if isinstance(item, (str, int, float)) and str(item)]


def _ordered_unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _short_hash(*parts: str) -> str:
    return hashlib.sha256(":".join(parts).encode("utf-8", errors="replace")).hexdigest()[:12]


def _query_signature(value: str) -> str:
    normalized = " ".join(str(value or "").lower().split())
    return _short_hash(normalized)
