from __future__ import annotations

import hashlib
import json
from dataclasses import replace

from kernel_v3.agent.answer_profile import answer_profile_from_dict, answer_quality_gaps
from kernel_v3.agent.contracts import AgentRuntimeResult
from kernel_v3.contracts import JsonObject
from kernel_v3.journal import JournalStore
from kernel_v3.journal_redaction import redact_journal_data
from kernel_v3.mission.contracts import (
    CoverageMap,
    MissionAssessment,
    MissionDirective,
    MissionIteration,
    MissionRequirement,
    MissionState,
)
from kernel_v3.mission.thread_rag import collect_run_delta
from kernel_v3.processors.contracts import MISSION_ASSESS_PROMPT_CONTRACT, MISSION_ASSESS_SCHEMA
from kernel_v3.processors.fabric import ProcessorFabric


HARD_BLOCK_REASONS = {
    "model_planner_processor_failed",
    "policy_or_tool_blocked",
    "tool_disabled",
    "blocked_side_effect_in_read_only_mode",
    "missing_permissions",
}


class MissionSupervisor:
    def __init__(
        self,
        *,
        journal: JournalStore,
        processor_fabric: ProcessorFabric | None = None,
        assessor_mode: str = "rule",
        max_iterations: int = 6,
        no_progress_iteration_limit: int = 6,
    ) -> None:
        self.journal = journal
        self.processor_fabric = processor_fabric
        self.assessor_mode = assessor_mode
        self.max_iterations = max(1, int(max_iterations))
        self.no_progress_iteration_limit = max(1, int(no_progress_iteration_limit))

    def start(self, *, root_goal: str, thread_id: str, metadata: JsonObject | None = None) -> MissionState:
        mission_id = _stable_id("mission", thread_id, root_goal)
        requirement = MissionRequirement(
            requirement_id=f"req-{_short_hash(root_goal)}",
            text=root_goal,
            status="open",
        )
        coverage = CoverageMap(
            mission_id=mission_id,
            coverage_score=0.0,
            requirements=[requirement.to_dict()],
            evidence_refs=[],
            citation_refs=[],
            missing_requirements=[requirement.text],
            diagnostics={},
        )
        state = MissionState(
            mission_id=mission_id,
            thread_id=thread_id,
            root_goal=root_goal,
            status="running",
            requirements=[requirement.to_dict()],
            coverage_map=coverage.to_dict(),
            attempted_strategies=[],
            open_gaps=[requirement.text],
            blocked_reasons=[],
            iteration_count=0,
            metadata=dict(metadata or {}),
        )
        self._append(
            task_id=None,
            run_id=f"mission-{_short_hash(mission_id)}",
            kind="mission_created",
            data=state.to_dict(),
            state_delta={"mission_id": mission_id, "mission_status": "running"},
        )
        return state

    def assess(self, mission: MissionState, result: AgentRuntimeResult, *, index: int) -> tuple[MissionState, MissionAssessment]:
        run_delta = collect_run_delta(self.journal, task_id=result.task_id, run_id=result.run_id)
        rule_assessment = self._rule_assessment(mission, result, run_delta=run_delta, index=index)
        model_assessment = self._model_assessment(mission, result, run_delta=run_delta, rule_assessment=rule_assessment)
        assessment = _merge_model_assessment(rule_assessment, model_assessment)
        iteration = MissionIteration(
            iteration_id=f"mission-iteration-{mission.mission_id}-{index}",
            mission_id=mission.mission_id,
            task_id=result.task_id,
            run_id=result.run_id,
            index=index,
            status=result.status,
            run_delta=run_delta,
            assessment=assessment.to_dict(),
        )
        updated = self._updated_state(mission, result, assessment, run_delta=run_delta)
        self._append(
            task_id=result.task_id,
            run_id=result.run_id,
            kind="mission_run_delta",
            data=run_delta,
            state_delta={"mission_id": mission.mission_id, "mission_iteration": index},
        )
        self._append(
            task_id=result.task_id,
            run_id=result.run_id,
            kind="mission_assessment",
            data=assessment.to_dict(),
            state_delta={"mission_id": mission.mission_id, "mission_decision": assessment.decision},
        )
        if assessment.next_directive is not None:
            self._append(
                task_id=result.task_id,
                run_id=result.run_id,
                kind="mission_directive",
                data=assessment.next_directive,
                state_delta={"mission_id": mission.mission_id, "mission_directive": "continue"},
            )
        self._append(
            task_id=result.task_id,
            run_id=result.run_id,
            kind="mission_iteration",
            data=iteration.to_dict(),
            state_delta={"mission_id": mission.mission_id, "mission_iteration_status": result.status},
        )
        if assessment.decision in {"final_answer", "failure_report", "ask_user", "blocked"}:
            self._append(
                task_id=result.task_id,
                run_id=result.run_id,
                kind="mission_decision",
                data={
                    "mission_id": mission.mission_id,
                    "decision": assessment.decision,
                    "reason": assessment.reason_summary,
                    "coverage_score": assessment.coverage_score,
                    "missing_requirements": list(assessment.missing_requirements),
                },
                state_delta={"mission_id": mission.mission_id, "mission_status": assessment.decision},
            )
        return updated, assessment

    def _rule_assessment(
        self,
        mission: MissionState,
        result: AgentRuntimeResult,
        *,
        run_delta: JsonObject,
        index: int,
    ) -> MissionAssessment:
        evidence_refs = _string_list(run_delta.get("evidence_refs"))
        citation_refs = _string_list(run_delta.get("citation_refs"))
        missing = _mission_missing_requirements(mission, result, run_delta=run_delta)
        coverage_score = _coverage_score(result, mission=mission, evidence_refs=evidence_refs, citation_refs=citation_refs, missing=missing)
        no_progress_count = _no_progress_count(mission) + (0 if _has_material_progress(result, run_delta) else 1)
        hard_block = _hard_block_reason(result)
        final_answer_covers_goal = _final_answer_covers_mission(result, mission=mission)
        can_continue = (
            (result.status != "completed" or (result.final_answer is not None and not final_answer_covers_goal))
            and hard_block is None
            and index < self.max_iterations
            and no_progress_count < self.no_progress_iteration_limit
        )
        if result.status == "completed" and result.final_answer is not None and final_answer_covers_goal:
            decision = "final_answer"
            reason = "mission_goal_covered_by_final_answer"
            next_directive = None
            missing = []
            coverage_score = max(coverage_score, 1.0)
        elif result.status == "needs_user_input" and not can_continue:
            decision = "ask_user"
            reason = "critical_user_input_required"
            next_directive = None
        elif hard_block is not None:
            decision = "blocked"
            reason = hard_block
            next_directive = None
        elif can_continue:
            decision = "continue"
            reason = "global_goal_not_covered_try_new_strategy"
            next_directive = _directive_for_gap(
                mission,
                result,
                run_delta=run_delta,
                missing=missing,
                index=index,
            ).to_dict()
        else:
            decision = "failure_report"
            reason = "mission_exhausted_without_sufficient_coverage"
            next_directive = None
        return MissionAssessment(
            assessment_id=f"mission-assessment-{mission.mission_id}-{index}",
            mission_id=mission.mission_id,
            task_id=result.task_id,
            run_id=result.run_id,
            decision=decision,
            coverage_score=round(min(1.0, coverage_score), 4),
            covered_requirements=[] if missing else [str(item.get("text")) for item in mission.requirements if item.get("text")],
            missing_requirements=missing,
            unsupported_claims=[],
            next_directive=next_directive,
            confidence=0.78 if decision == "continue" else 0.86,
            reason_summary=reason,
            diagnostics={
                "no_progress_count": no_progress_count,
                "max_iterations": self.max_iterations,
                "has_material_progress": _has_material_progress(result, run_delta),
                "hard_block": hard_block,
            },
        )

    def _model_assessment(
        self,
        mission: MissionState,
        result: AgentRuntimeResult,
        *,
        run_delta: JsonObject,
        rule_assessment: MissionAssessment,
    ) -> JsonObject | None:
        if self.assessor_mode != "model" or self.processor_fabric is None:
            return None
        payload = {
            "contract": MISSION_ASSESS_PROMPT_CONTRACT,
            "mission_state": mission.to_dict(),
            "agent_result": result.to_dict(),
            "run_delta": run_delta,
            "host_rule_assessment": rule_assessment.to_dict(),
        }
        outcome = self.processor_fabric.run_json(
            task_type="mission.assess",
            task_id=result.task_id,
            run_id=result.run_id,
            context_id=f"mission:{mission.mission_id}:{result.run_id}",
            prompt=json.dumps(payload, ensure_ascii=False, sort_keys=True),
            schema=MISSION_ASSESS_SCHEMA,
            parameters={"adapter": "MissionSupervisor"},
        )
        return outcome.parsed

    def _updated_state(
        self,
        mission: MissionState,
        result: AgentRuntimeResult,
        assessment: MissionAssessment,
        *,
        run_delta: JsonObject,
    ) -> MissionState:
        evidence_refs = _ordered_unique([
            *_string_list(mission.coverage_map.get("evidence_refs") if isinstance(mission.coverage_map, dict) else []),
            *_string_list(run_delta.get("evidence_refs")),
        ])
        citation_refs = _ordered_unique([
            *_string_list(mission.coverage_map.get("citation_refs") if isinstance(mission.coverage_map, dict) else []),
            *_string_list(run_delta.get("citation_refs")),
        ])
        requirements = [
            _updated_requirement(item, assessment)
            for item in mission.requirements
            if isinstance(item, dict)
        ]
        coverage = CoverageMap(
            mission_id=mission.mission_id,
            coverage_score=assessment.coverage_score,
            requirements=requirements,
            evidence_refs=evidence_refs,
            citation_refs=citation_refs,
            missing_requirements=list(assessment.missing_requirements),
            diagnostics=dict(assessment.diagnostics),
        )
        attempted = _ordered_unique([
            *mission.attempted_strategies,
            *_strategy_names(run_delta),
            _directive_strategy(assessment.next_directive),
        ])
        metadata = dict(mission.metadata)
        if not _has_material_progress(result, run_delta):
            metadata["no_progress_count"] = int(metadata.get("no_progress_count") or 0) + 1
        else:
            metadata["no_progress_count"] = 0
        return replace(
            mission,
            status=_mission_status_from_decision(assessment.decision),
            coverage_map=coverage.to_dict(),
            attempted_strategies=[item for item in attempted if item],
            open_gaps=list(assessment.missing_requirements),
            blocked_reasons=_ordered_unique([*mission.blocked_reasons, *([assessment.reason_summary] if assessment.decision == "blocked" else [])]),
            iteration_count=mission.iteration_count + 1,
            active_task_id=result.task_id,
            last_run_id=result.run_id,
            directive=assessment.next_directive,
            metadata=metadata,
        )

    def _append(self, *, task_id: str | None, run_id: str, kind: str, data: JsonObject, state_delta: JsonObject | None = None) -> None:
        self.journal.append(
            task_id=task_id,
            run_id=run_id,
            step_id=None,
            kind=kind,
            data=redact_journal_data(data),
            state_delta=dict(state_delta or {}),
        )


def _merge_model_assessment(rule: MissionAssessment, model: JsonObject | None) -> MissionAssessment:
    if not isinstance(model, dict):
        return rule
    decision = str(model.get("decision") or rule.decision)
    if decision not in {"continue", "final_answer", "ask_user", "failure_report", "blocked"}:
        decision = rule.decision
    if rule.decision in {"blocked", "failure_report"} and decision == "continue":
        decision = rule.decision
    if decision == "final_answer" and rule.decision != "final_answer":
        decision = rule.decision
    next_directive = model.get("next_directive") if isinstance(model.get("next_directive"), dict) else rule.next_directive
    return replace(
        rule,
        decision=decision,
        coverage_score=_float_between(model.get("coverage_score"), default=rule.coverage_score),
        covered_requirements=_string_list(model.get("covered_requirements")) or rule.covered_requirements,
        missing_requirements=_string_list(model.get("missing_requirements")) or rule.missing_requirements,
        unsupported_claims=_string_list(model.get("unsupported_claims")),
        next_directive=dict(next_directive) if isinstance(next_directive, dict) else None,
        confidence=_float_between(model.get("confidence"), default=rule.confidence),
        reason_summary=str(model.get("reason_summary") or rule.reason_summary),
        model_decision=dict(model),
    )


def _directive_for_gap(
    mission: MissionState,
    result: AgentRuntimeResult,
    *,
    run_delta: JsonObject,
    missing: list[str],
    index: int,
) -> MissionDirective:
    attempted_queries = _attempted_queries(run_delta)
    failure = result.failure_report if isinstance(result.failure_report, dict) else {}
    next_action = str(failure.get("next_possible_action") or "try_materially_new_strategy")
    strategy = _next_strategy(run_delta, next_action=next_action)
    gap = missing[0] if missing else mission.root_goal
    return MissionDirective(
        directive_id=f"mission-directive-{mission.mission_id}-{index}",
        mission_id=mission.mission_id,
        root_goal=mission.root_goal,
        strategy=strategy,
        next_subgoal=gap,
        missing_requirements=missing,
        avoid_repeating=attempted_queries,
        suggested_actions=[
            {
                "kind": "replan",
                "strategy": strategy,
                "instruction": "Propose a materially different safe action that advances the root goal.",
            }
        ],
        stop_conditions=[
            "mission_coverage_sufficient",
            "explicit_user_interrupt",
            "hard_policy_block",
            "repeated_no_new_coverage",
        ],
        reason=f"{result.status}:{next_action}",
        metadata={"source_run_id": result.run_id, "source_task_id": result.task_id},
    )


def _mission_missing_requirements(mission: MissionState, result: AgentRuntimeResult, *, run_delta: JsonObject) -> list[str]:
    missing: list[str] = []
    if result.status == "completed" and result.final_answer is not None and not _final_answer_covers_mission(result, mission=mission):
        missing.extend(_final_answer_missing_requirements(result, mission=mission))
    failure = result.failure_report if isinstance(result.failure_report, dict) else {}
    missing.extend(_string_list(failure.get("missing_evidence")))
    for feedback in run_delta.get("feedback", []) if isinstance(run_delta.get("feedback"), list) else []:
        if isinstance(feedback, dict):
            missing.extend(_string_list(feedback.get("missing_evidence")))
    if result.status == "failed" and not missing:
        reason = failure.get("reason") or "mission_goal_uncovered"
        missing.append(str(reason))
    if result.status != "completed" and not missing:
        missing.extend(mission.open_gaps or [mission.root_goal])
    return _ordered_unique([item for item in missing if item and item != "remaining_plan_actions"])


def _coverage_score(
    result: AgentRuntimeResult,
    *,
    mission: MissionState,
    evidence_refs: list[str],
    citation_refs: list[str],
    missing: list[str],
) -> float:
    if result.status == "completed" and result.final_answer is not None and _final_answer_covers_mission(result, mission=mission):
        return 1.0
    score = 0.0
    if evidence_refs:
        score += 0.32
    if citation_refs:
        score += 0.38
    if result.status == "needs_user_input":
        score += 0.05
    if result.status == "failed":
        score += 0.04
    if not missing:
        score += 0.2
    return score


def _has_material_progress(result: AgentRuntimeResult, run_delta: JsonObject) -> bool:
    if result.status == "completed" and result.final_answer is not None and _final_answer_covers_mission(result, mission=None):
        return True
    if _string_list(run_delta.get("evidence_refs")) or _string_list(run_delta.get("citation_refs")):
        return True
    for report in run_delta.get("retrieval_reports", []) if isinstance(run_delta.get("retrieval_reports"), list) else []:
        if not isinstance(report, dict):
            continue
        rejected_count = report.get("rejected_evidence_count")
        if isinstance(rejected_count, int) and rejected_count > 0:
            return True
    return False


def _final_answer_covers_mission(result: AgentRuntimeResult, *, mission: MissionState | None) -> bool:
    final_answer = result.final_answer if isinstance(result.final_answer, dict) else {}
    if not final_answer:
        return False
    confidence = _float_between(final_answer.get("confidence"), default=0.0)
    if confidence <= 0.05:
        return False
    if result.mode == "retrieval_answer":
        citation_refs = _string_list(final_answer.get("citation_refs"))
        used_evidence = _string_list(final_answer.get("used_evidence"))
        if not citation_refs and not used_evidence:
            return False
    if _final_answer_quality_gaps(result, mission=mission):
        return False
    return True


def _final_answer_missing_requirements(result: AgentRuntimeResult, *, mission: MissionState | None) -> list[str]:
    final_answer = result.final_answer if isinstance(result.final_answer, dict) else {}
    missing: list[str] = []
    confidence = _float_between(final_answer.get("confidence"), default=0.0)
    if confidence <= 0.05:
        missing.append("supported_final_answer")
    if result.mode == "retrieval_answer":
        if not _string_list(final_answer.get("citation_refs")):
            missing.append("citation_refs")
        if not _string_list(final_answer.get("used_evidence")):
            missing.append("used_evidence")
    missing.extend(_final_answer_quality_gaps(result, mission=mission))
    return missing or ["mission_goal_uncovered_by_final_answer"]


def _final_answer_quality_gaps(result: AgentRuntimeResult, *, mission: MissionState | None) -> list[str]:
    final_answer = result.final_answer if isinstance(result.final_answer, dict) else {}
    if not final_answer:
        return []
    profile_data = None
    if mission is not None and isinstance(mission.metadata, dict):
        profile_data = mission.metadata.get("answer_profile")
    profile = answer_profile_from_dict(profile_data)
    return answer_quality_gaps(
        str(final_answer.get("answer") or ""),
        profile=profile,
        citation_refs=_string_list(final_answer.get("citation_refs")),
        used_evidence=_string_list(final_answer.get("used_evidence")),
    )


def _hard_block_reason(result: AgentRuntimeResult) -> str | None:
    failure = result.failure_report if isinstance(result.failure_report, dict) else {}
    reason = str(failure.get("reason") or "")
    if reason in HARD_BLOCK_REASONS:
        return reason
    if reason.startswith("missing_permissions"):
        return reason
    return None


def _updated_requirement(item: JsonObject, assessment: MissionAssessment) -> JsonObject:
    text = str(item.get("text") or "")
    missing = set(assessment.missing_requirements)
    status = "covered" if assessment.decision == "final_answer" or (text and text not in missing) else "open"
    return {
        **item,
        "status": status,
        "missing_reason": None if status == "covered" else (assessment.missing_requirements[0] if assessment.missing_requirements else None),
    }


def _mission_status_from_decision(decision: str) -> str:
    if decision == "continue":
        return "running"
    if decision == "final_answer":
        return "completed"
    if decision == "ask_user":
        return "needs_user_input"
    if decision == "blocked":
        return "blocked"
    return "failed"


def _no_progress_count(mission: MissionState) -> int:
    value = mission.metadata.get("no_progress_count") if isinstance(mission.metadata, dict) else 0
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _strategy_names(run_delta: JsonObject) -> list[str]:
    names: list[str] = []
    for action in run_delta.get("actions", []) if isinstance(run_delta.get("actions"), list) else []:
        if not isinstance(action, dict):
            continue
        name = action.get("name") or action.get("action_kind")
        if isinstance(name, str) and name:
            names.append(name)
    return names


def _directive_strategy(value: JsonObject | None) -> str:
    if not isinstance(value, dict):
        return ""
    strategy = value.get("strategy")
    return str(strategy) if isinstance(strategy, str) else ""


def _next_strategy(run_delta: JsonObject, *, next_action: str) -> str:
    report_statuses = [
        str(item.get("status"))
        for item in run_delta.get("retrieval_reports", [])
        if isinstance(item, dict) and item.get("status")
    ]
    if "insufficient" in " ".join(report_statuses) or "retrieval" in next_action:
        return "broaden_or_change_retrieval_strategy"
    if "budget" in next_action:
        return "reduce_cost_or_focus_high_authority_sources"
    return next_action or "try_materially_new_strategy"


def _attempted_queries(run_delta: JsonObject) -> list[str]:
    queries: list[str] = []
    for report in run_delta.get("retrieval_reports", []) if isinstance(run_delta.get("retrieval_reports"), list) else []:
        if not isinstance(report, dict):
            continue
        preview = report.get("preview")
        if isinstance(preview, str) and preview:
            queries.append(preview)
    return _ordered_unique(queries)


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if isinstance(item, (str, int, float)) and str(item)]


def _ordered_unique(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def _float_between(value: object, *, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return max(0.0, min(1.0, parsed))


def _stable_id(prefix: str, *parts: str) -> str:
    return f"{prefix}-{_short_hash(':'.join(parts))}"


def _short_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()[:12]
