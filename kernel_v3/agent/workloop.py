from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field

from kernel_v3.agent.contracts import TaskRecipe
from kernel_v3.contracts import Contract, Feedback, JsonObject, Observation
from kernel_v3.evaluator import Evaluator
from kernel_v3.journal import JournalStore


@dataclass(frozen=True, kw_only=True)
class WorkloopState(Contract):
    task_id: str
    run_id: str
    step_id: str | None
    iteration_index: int
    action_count: int
    observation_count: int
    artifact_count: int
    evidence_count: int
    citation_count: int
    missing_evidence: list[str]
    failure_reasons: list[str]


@dataclass(frozen=True, kw_only=True)
class WorkloopIteration(Contract):
    iteration_id: str
    task_id: str
    run_id: str
    step_id: str | None
    action_ref: str | None
    observation_ref: str | None
    feedback_status: str | None


@dataclass(frozen=True, kw_only=True)
class ProgressSignal(Contract):
    signal_type: str
    ref: str
    weight: float
    diagnostics: JsonObject = field(default_factory=dict)


@dataclass(frozen=True, kw_only=True)
class ProgressAssessment(Contract):
    assessment_id: str
    task_id: str
    run_id: str
    step_id: str | None
    made_progress: bool
    progress_score: float
    progress_type: str
    new_refs: list[str]
    signals: list[JsonObject]


@dataclass(frozen=True, kw_only=True)
class RepetitionSignal(Contract):
    signal_id: str
    task_id: str
    run_id: str
    step_id: str | None
    repeated: bool
    repeat_type: str | None
    repeat_count: int
    threshold: int
    repeated_refs: list[str]
    diagnostics: JsonObject = field(default_factory=dict)


@dataclass(frozen=True, kw_only=True)
class EvidenceSufficiency(Contract):
    sufficiency_id: str
    task_id: str
    run_id: str
    step_id: str | None
    sufficient: bool
    citations_required: bool
    evidence_count: int
    citation_count: int
    valid_citation_refs: list[str]
    missing: list[str]
    reason: str
    diagnostics: JsonObject = field(default_factory=dict)


@dataclass(frozen=True, kw_only=True)
class TerminationDecision(Contract):
    decision_id: str
    task_id: str
    run_id: str
    step_id: str | None
    decision: str
    reason: str
    feedback_status: str
    override: bool
    diagnostics: JsonObject = field(default_factory=dict)


@dataclass(frozen=True, kw_only=True)
class WorkloopConfig:
    repeated_action_limit: int = 2
    repeated_missing_evidence_limit: int = 2
    no_progress_step_limit: int = 2


class WorkloopEvaluator:
    def __init__(
        self,
        *,
        inner: Evaluator,
        journal: JournalStore,
        recipe: TaskRecipe,
        config: WorkloopConfig | None = None,
    ) -> None:
        self.inner = inner
        self.journal = journal
        self.recipe = recipe
        self.config = config or WorkloopConfig()
        self.calls = 0

    def evaluate(self, context, observation: Observation) -> Feedback:
        self.calls += 1
        task_id = str(context.state["task_id"])
        run_id = str(context.state["run_id"])
        step_id = _observation_step(self.journal, task_id=task_id, observation_id=observation.observation_id)
        base = self.inner.evaluate(context, observation)
        progress = assess_progress(
            self.journal,
            task_id=task_id,
            run_id=run_id,
            step_id=step_id,
            observation=observation,
        )
        repetition = detect_repetition(
            self.journal,
            task_id=task_id,
            run_id=run_id,
            step_id=step_id,
            config=self.config,
            latest_missing_evidence=list(base.missing_evidence),
        )
        evidence = assess_evidence_sufficiency(
            self.journal,
            task_id=task_id,
            run_id=run_id,
            step_id=step_id,
            recipe=self.recipe,
        )
        decision = decide_termination(
            feedback=base,
            progress=progress,
            repetition=repetition,
            evidence=evidence,
            recipe=self.recipe,
            no_progress_count=_recent_no_progress_count(self.journal, task_id=task_id, run_id=run_id) + (0 if progress.made_progress else 1),
            config=self.config,
        )
        _append_workloop_records(
            self.journal,
            task_id=task_id,
            run_id=run_id,
            step_id=step_id,
            progress=progress,
            repetition=repetition,
            evidence=evidence,
            decision=decision,
        )
        return _feedback_from_decision(base, decision, run_id=run_id, index=self.calls)


def workloop_state(journal: JournalStore, *, task_id: str, run_id: str, step_id: str | None = None) -> WorkloopState:
    records = [record for record in journal.records(task_id=task_id) if record.run_id == run_id]
    return WorkloopState(
        task_id=task_id,
        run_id=run_id,
        step_id=step_id,
        iteration_index=len([record for record in records if record.kind == "termination_decision"]) + 1,
        action_count=len([record for record in records if record.kind == "action"]),
        observation_count=len([record for record in records if record.kind == "observation"]),
        artifact_count=len({artifact for record in records for artifact in record.artifact_refs}),
        evidence_count=len([record for record in records if record.kind == "retrieval_evidence"]),
        citation_count=len([record for record in records if record.kind == "retrieval_citation"]),
        missing_evidence=_latest_missing_evidence(journal, task_id=task_id, run_id=run_id),
        failure_reasons=_failure_reasons(journal, task_id=task_id, run_id=run_id),
    )


def assess_progress(
    journal: JournalStore,
    *,
    task_id: str,
    run_id: str,
    step_id: str | None,
    observation: Observation,
) -> ProgressAssessment:
    current_action = _latest_record(journal, task_id=task_id, kind="action")
    action_ref = current_action.action_ref if current_action is not None else None
    signals: list[ProgressSignal] = []
    if observation.status == "ok":
        signals.append(ProgressSignal(signal_type="new_observation", ref=observation.observation_id, weight=0.15))
    current_records = [
        record for record in journal.records(task_id=task_id)
        if record.run_id == run_id and (record.step_id == step_id or (action_ref and record.action_ref == action_ref))
    ]
    for record in current_records:
        for artifact_id in record.artifact_refs:
            if not _seen_artifact_before(journal, task_id=task_id, record_id=record.record_id, artifact_id=artifact_id):
                signals.append(ProgressSignal(signal_type="new_artifact", ref=artifact_id, weight=0.2))
        if record.kind == "retrieval_evidence":
            signals.append(ProgressSignal(signal_type="new_evidence", ref=str(record.data.get("evidence_id", record.record_id)), weight=0.35))
        elif record.kind == "retrieval_citation":
            signals.append(ProgressSignal(signal_type="new_citation", ref=str(record.data.get("citation_id", record.record_id)), weight=0.4))
        elif record.kind == "observation" and record.data.get("source") == "tool:file.read" and record.data.get("status") == "ok":
            content = record.data.get("content")
            path = content.get("path") if isinstance(content, dict) else None
            signals.append(ProgressSignal(signal_type="new_file_read", ref=str(path or record.record_id), weight=0.35))
        elif record.kind == "observation" and record.data.get("source") == "tool:workspace.write" and record.data.get("status") == "ok":
            content = record.data.get("content")
            path = content.get("path") if isinstance(content, dict) else None
            signals.append(ProgressSignal(signal_type="new_file_write", ref=str(path or record.record_id), weight=0.45))
        elif record.kind == "observation" and record.data.get("source") == "tool:system.time" and record.data.get("status") == "ok":
            signals.append(ProgressSignal(signal_type="new_system_observation", ref=record.record_id, weight=0.35))
        elif record.kind == "retrieval_search_attempt" and record.data.get("status") == "failed":
            signals.append(ProgressSignal(signal_type="new_failure_diagnostic", ref=record.record_id, weight=0.1))
    if observation.status not in {"blocked", "failed"} and current_action is not None and _action_narrows_scope(current_action.data):
        signals.append(ProgressSignal(signal_type="narrowed_scope", ref=current_action.record_id, weight=0.1))
    if observation.status == "needs_user_input":
        signals.append(ProgressSignal(signal_type="new_user_input_requirement", ref=observation.observation_id, weight=0.1))
    score = min(1.0, sum(signal.weight for signal in signals))
    progress_type = _strongest_signal(signals)
    refs = _ordered_unique([signal.ref for signal in signals])
    return ProgressAssessment(
        assessment_id=f"progress-{run_id}-{step_id or 'final'}",
        task_id=task_id,
        run_id=run_id,
        step_id=step_id,
        made_progress=score > 0,
        progress_score=round(score, 4),
        progress_type=progress_type,
        new_refs=refs,
        signals=[signal.to_dict() for signal in signals],
    )


def detect_repetition(
    journal: JournalStore,
    *,
    task_id: str,
    run_id: str,
    step_id: str | None,
    config: WorkloopConfig,
    latest_missing_evidence: list[str],
) -> RepetitionSignal:
    checks = [
        _repeat_for_values(_retrieval_queries(journal, task_id=task_id, run_id=run_id), threshold=config.repeated_action_limit, repeat_type="same_retrieval_query"),
        _repeat_for_values(_action_fingerprints(journal, task_id=task_id, run_id=run_id), threshold=config.repeated_action_limit, repeat_type="same_action_payload"),
        _repeat_for_values(_file_paths(journal, task_id=task_id, run_id=run_id), threshold=config.repeated_action_limit, repeat_type="same_file_path"),
        _repeat_for_values(_observation_hashes(journal, task_id=task_id, run_id=run_id), threshold=config.repeated_action_limit, repeat_type="same_observation_hash"),
        _repeat_for_values(_missing_evidence_values(journal, task_id=task_id, run_id=run_id, latest=latest_missing_evidence), threshold=config.repeated_missing_evidence_limit, repeat_type="same_missing_evidence"),
        _repeat_for_values(_failure_reason_values(journal, task_id=task_id, run_id=run_id), threshold=config.repeated_missing_evidence_limit, repeat_type="same_failure_reason"),
    ]
    repeated = next((item for item in checks if item is not None), None)
    if repeated is None:
        return RepetitionSignal(
            signal_id=f"repetition-{run_id}-{step_id or 'final'}",
            task_id=task_id,
            run_id=run_id,
            step_id=step_id,
            repeated=False,
            repeat_type=None,
            repeat_count=0,
            threshold=config.repeated_action_limit,
            repeated_refs=[],
        )
    repeat_type, repeat_count, threshold, refs = repeated
    return RepetitionSignal(
        signal_id=f"repetition-{run_id}-{step_id or 'final'}",
        task_id=task_id,
        run_id=run_id,
        step_id=step_id,
        repeated=True,
        repeat_type=repeat_type,
        repeat_count=repeat_count,
        threshold=threshold,
        repeated_refs=refs,
    )


def assess_evidence_sufficiency(
    journal: JournalStore,
    *,
    task_id: str,
    run_id: str,
    step_id: str | None,
    recipe: TaskRecipe,
) -> EvidenceSufficiency:
    retrieval_evidence = [
        record for record in journal.records(task_id=task_id, kind="retrieval_evidence")
        if record.run_id == run_id
    ]
    retrieval_citations = [
        record for record in journal.records(task_id=task_id, kind="retrieval_citation")
        if record.run_id == run_id
    ]
    workspace_reads = [
        record for record in journal.records(task_id=task_id, kind="observation")
        if record.run_id == run_id
        and record.data.get("source") == "tool:file.read"
        and record.data.get("status") == "ok"
    ]
    workspace_writes = [
        record for record in journal.records(task_id=task_id, kind="observation")
        if record.run_id == run_id
        and record.data.get("source") == "tool:workspace.write"
        and record.data.get("status") == "ok"
    ]
    system_observations = [
        record for record in journal.records(task_id=task_id, kind="observation")
        if record.run_id == run_id
        and record.data.get("source") == "tool:system.time"
        and record.data.get("status") == "ok"
    ]
    latest_retrieval_report = _latest_run_record(
        journal,
        task_id=task_id,
        run_id=run_id,
        kind="retrieval_report",
    )
    planned_retrieval_coverage = _planned_retrieval_coverage(
        journal,
        task_id=task_id,
        run_id=run_id,
        recipe=recipe,
    )
    report_diagnostics = _dict_or_empty(latest_retrieval_report.data.get("diagnostics")) if latest_retrieval_report else {}
    evaluation_diagnostics = _dict_or_empty(report_diagnostics.get("evaluation_diagnostics"))
    missing_query_facets = _string_list(evaluation_diagnostics.get("missing_query_facets"))
    source_authority = _dict_or_empty(evaluation_diagnostics.get("source_authority"))
    source_authority_requirement = _string_or_empty(evaluation_diagnostics.get("source_authority_requirement"))
    missing_source_authority = _missing_source_authority(
        requirement=source_authority_requirement,
        authority_summary=source_authority,
    )
    latest_report_status = str(latest_retrieval_report.data.get("status")) if latest_retrieval_report else None
    latest_report_reason = str(report_diagnostics.get("reason") or latest_report_status or "")
    latest_observation = _latest_record(journal, task_id=task_id, kind="observation")
    if (
        latest_observation is not None
        and latest_observation.run_id == run_id
        and latest_observation.data.get("status") == "needs_user_input"
    ):
        return EvidenceSufficiency(
            sufficiency_id=f"evidence-{run_id}-{step_id or 'final'}",
            task_id=task_id,
            run_id=run_id,
            step_id=step_id,
            sufficient=False,
            citations_required=recipe.citations_required,
            evidence_count=0,
            citation_count=0,
            valid_citation_refs=[],
            missing=["user_input"],
            reason="user_input_required",
            diagnostics={
                "workspace_read_count": len(workspace_reads),
                "workspace_write_count": len(workspace_writes),
                "system_observation_count": len(system_observations),
                "retrieval_evidence_count": len(retrieval_evidence),
            },
        )
    evidence_count = len(retrieval_evidence) + len(workspace_reads) + len(workspace_writes) + len(system_observations)
    citation_refs = [str(record.data.get("citation_id")) for record in retrieval_citations if record.data.get("citation_id")]
    citation_refs.extend(f"workspace-cite-{index}" for index, _ in enumerate(workspace_reads, start=1))
    missing: list[str] = []
    sufficient = True
    reason = "sufficient"
    if recipe.mode in {"direct_answer", "semantic_answer"} and not recipe.citations_required:
        return EvidenceSufficiency(
            sufficiency_id=f"evidence-{run_id}-{step_id or 'final'}",
            task_id=task_id,
            run_id=run_id,
            step_id=step_id,
            sufficient=True,
            citations_required=False,
            evidence_count=evidence_count,
            citation_count=len(citation_refs),
            valid_citation_refs=_ordered_unique(citation_refs),
            missing=[],
            reason=f"{recipe.mode}_does_not_require_evidence",
        )
    if recipe.citations_required and not citation_refs:
        sufficient = False
        missing.append("citation_refs")
        reason = "citations_required_but_missing"
    if recipe.mode == "retrieval_answer" and not retrieval_evidence:
        sufficient = False
        missing.append("retrieval_evidence")
        reason = "missing_retrieval_evidence"
    if recipe.mode == "retrieval_answer" and latest_report_status and latest_report_status != "sufficient":
        sufficient = False
        missing.append("sufficient_retrieval_evidence")
        missing.extend(f"query_facet:{facet}" for facet in missing_query_facets)
        missing.extend(missing_source_authority)
        reason = latest_report_reason or f"retrieval_{latest_report_status}"
    if recipe.mode == "retrieval_answer" and planned_retrieval_coverage.get("required") is True:
        incomplete_goal_ids = _string_list(planned_retrieval_coverage.get("incomplete_goal_ids"))
        if incomplete_goal_ids:
            sufficient = False
            missing.append("sufficient_retrieval_evidence")
            missing.extend(f"retrieval_subgoal:{goal_id}" for goal_id in incomplete_goal_ids)
            reason = "planned_retrieval_subgoals_incomplete"
    if recipe.mode == "workspace_answer" and not workspace_reads:
        sufficient = False
        missing.append("file_read_observation")
        reason = "missing_workspace_file_observation"
    if recipe.mode == "workspace_write" and not workspace_writes:
        sufficient = False
        missing.append("workspace_write_observation")
        reason = "missing_workspace_write_observation"
    if recipe.mode == "system_answer" and not system_observations:
        sufficient = False
        missing.append("system_observation")
        reason = "missing_system_observation"
    return EvidenceSufficiency(
        sufficiency_id=f"evidence-{run_id}-{step_id or 'final'}",
        task_id=task_id,
        run_id=run_id,
        step_id=step_id,
        sufficient=sufficient,
        citations_required=recipe.citations_required,
        evidence_count=evidence_count,
        citation_count=len(citation_refs),
        valid_citation_refs=_ordered_unique(citation_refs),
        missing=_ordered_unique(missing),
        reason=reason,
        diagnostics={
            "workspace_read_count": len(workspace_reads),
            "workspace_write_count": len(workspace_writes),
            "system_observation_count": len(system_observations),
            "retrieval_evidence_count": len(retrieval_evidence),
            "latest_retrieval_report_status": latest_report_status,
            "latest_retrieval_report_reason": latest_report_reason,
            "missing_query_facets": missing_query_facets,
            "source_authority_requirement": source_authority_requirement,
            "source_authority": source_authority,
            "missing_source_authority": missing_source_authority,
            "planned_retrieval_coverage": planned_retrieval_coverage,
        },
    )


def decide_termination(
    *,
    feedback: Feedback,
    progress: ProgressAssessment,
    repetition: RepetitionSignal,
    evidence: EvidenceSufficiency,
    recipe: TaskRecipe,
    no_progress_count: int,
    config: WorkloopConfig,
) -> TerminationDecision:
    override = False
    decision = feedback.status
    reason = feedback.stop_reason or feedback.status
    if feedback.status == "final_answer_ready":
        if evidence.sufficient:
            decision = "final_answer"
            reason = "evidence_sufficient"
        elif not recipe.allowed_tools:
            decision = "failure_report"
            reason = evidence.reason
            override = True
        else:
            decision = "continue"
            reason = "final_answer_blocked_by_evidence"
            override = True
    elif feedback.status == "continue":
        if "remaining_plan_actions" in feedback.missing_evidence:
            decision = "continue"
            reason = "planned_actions_remaining"
        elif evidence.sufficient and recipe.mode in {
            "semantic_answer",
            "retrieval_answer",
            "workspace_answer",
            "workspace_write",
            "system_answer",
        }:
            decision = "final_answer"
            reason = "evidence_sufficient_overrode_continue"
            override = True
        else:
            decision = "continue"
            reason = "evaluator_continue"
    elif feedback.status == "needs_user_input":
        decision = "ask_user"
        reason = "user_input_required"
    elif feedback.status == "blocked":
        decision = "blocked"
        reason = "policy_or_tool_blocked"
    elif feedback.status in {"failed", "step_limit_exceeded"}:
        if not evidence.sufficient and feedback.status == "failed" and recipe.allowed_tools:
            decision = "continue"
            reason = "insufficient_evidence_retry"
            override = True
        else:
            decision = "failure_report"
            reason = feedback.stop_reason or feedback.status
    if repetition.repeated and not _allows_repeated_signal_to_continue(feedback=feedback, repetition=repetition):
        decision = "failure_report"
        reason = "repeated_missing_evidence" if repetition.repeat_type == "same_missing_evidence" else "repeated_no_progress"
        override = True
    if not progress.made_progress and no_progress_count >= config.no_progress_step_limit:
        decision = "failure_report"
        reason = "repeated_no_progress"
        override = True
    if recipe.mode == "clarify_first":
        decision = "ask_user"
        reason = "clarification_required"
        override = feedback.status != "needs_user_input"
    return TerminationDecision(
        decision_id=f"termination-{progress.run_id}-{progress.step_id or 'final'}",
        task_id=progress.task_id,
        run_id=progress.run_id,
        step_id=progress.step_id,
        decision=decision,
        reason=reason,
        feedback_status=feedback.status,
        override=override,
        diagnostics={
            "progress_score": progress.progress_score,
            "progress_type": progress.progress_type,
            "evidence_reason": evidence.reason,
            "evidence_missing": evidence.missing,
            "no_progress_count": no_progress_count,
        },
    )


def _allows_repeated_signal_to_continue(*, feedback: Feedback, repetition: RepetitionSignal) -> bool:
    if repetition.repeat_type != "same_missing_evidence":
        return False
    return "remaining_plan_actions" in feedback.missing_evidence


def _feedback_from_decision(base: Feedback, decision: TerminationDecision, *, run_id: str, index: int) -> Feedback:
    missing_evidence = _ordered_unique([*base.missing_evidence, *_decision_missing_evidence(decision)])
    if decision.decision == "continue":
        return Feedback(
            feedback_id=f"fb-{run_id}-workloop-{index}",
            run_id=run_id,
            status="continue",
            stop_reason=None,
            answer=None,
            missing_evidence=missing_evidence,
        )
    if decision.decision == "final_answer":
        return Feedback(
            feedback_id=f"fb-{run_id}-workloop-{index}",
            run_id=run_id,
            status="final_answer_ready",
            stop_reason="completed",
            answer=base.answer,
            missing_evidence=[],
        )
    if decision.decision == "ask_user":
        return Feedback(
            feedback_id=f"fb-{run_id}-workloop-{index}",
            run_id=run_id,
            status="needs_user_input",
            stop_reason="needs_user_input",
            answer=base.answer,
            missing_evidence=missing_evidence,
        )
    if decision.decision == "blocked":
        return Feedback(
            feedback_id=f"fb-{run_id}-workloop-{index}",
            run_id=run_id,
            status="blocked",
            stop_reason=decision.reason,
            answer=None,
            missing_evidence=missing_evidence,
        )
    return Feedback(
        feedback_id=f"fb-{run_id}-workloop-{index}",
        run_id=run_id,
        status="failed",
        stop_reason=decision.reason,
        answer=None,
        missing_evidence=missing_evidence or [decision.reason],
    )


def _append_workloop_records(
    journal: JournalStore,
    *,
    task_id: str,
    run_id: str,
    step_id: str | None,
    progress: ProgressAssessment,
    repetition: RepetitionSignal,
    evidence: EvidenceSufficiency,
    decision: TerminationDecision,
) -> None:
    journal.append(task_id=task_id, run_id=run_id, step_id=step_id, kind="progress_assessment", data=progress.to_dict(), state_delta={"made_progress": progress.made_progress})
    journal.append(task_id=task_id, run_id=run_id, step_id=step_id, kind="repetition_signal", data=repetition.to_dict(), state_delta={"repeated": repetition.repeated})
    journal.append(task_id=task_id, run_id=run_id, step_id=step_id, kind="evidence_sufficiency", data=evidence.to_dict(), state_delta={"evidence_sufficient": evidence.sufficient})
    journal.append(task_id=task_id, run_id=run_id, step_id=step_id, kind="termination_decision", data=decision.to_dict(), state_delta={"termination_decision": decision.decision, "termination_reason": decision.reason})


def _observation_step(journal: JournalStore, *, task_id: str, observation_id: str) -> str | None:
    for record in reversed(journal.records(task_id=task_id, kind="observation")):
        if record.observation_ref == observation_id or record.data.get("observation_id") == observation_id:
            return record.step_id
    return None


def _latest_record(journal: JournalStore, *, task_id: str, kind: str):
    records = journal.records(task_id=task_id, kind=kind)
    return records[-1] if records else None


def _latest_run_record(journal: JournalStore, *, task_id: str, run_id: str, kind: str):
    records = [
        record for record in journal.records(task_id=task_id, kind=kind)
        if record.run_id == run_id
    ]
    return records[-1] if records else None


def _planned_retrieval_coverage(journal: JournalStore, *, task_id: str, run_id: str, recipe: TaskRecipe) -> JsonObject:
    planned_goal_ids: list[str] = _planned_retrieval_goal_ids_from_recipe(recipe)
    for record in journal.records(task_id=task_id, kind="action"):
        if record.run_id != run_id:
            continue
        if record.data.get("name") != "retrieval.run":
            continue
        payload = record.data.get("payload")
        if not isinstance(payload, dict):
            continue
        goal_id = payload.get("goal_id")
        if isinstance(goal_id, str) and goal_id.startswith("goal-plan-"):
            planned_goal_ids.append(goal_id)
    planned_goal_ids = _ordered_unique(planned_goal_ids)
    if not planned_goal_ids:
        return {
            "required": False,
            "sufficient": True,
            "planned_goal_ids": [],
            "complete_goal_ids": [],
            "incomplete_goal_ids": [],
            "latest_status_by_goal_id": {},
        }
    reports_by_goal: dict[str, JsonObject] = {}
    for record in journal.records(task_id=task_id, kind="retrieval_report"):
        if record.run_id != run_id:
            continue
        goal_id = record.data.get("goal_id")
        if isinstance(goal_id, str):
            reports_by_goal[goal_id] = dict(record.data)
    incomplete: list[str] = []
    statuses: JsonObject = {}
    for goal_id in planned_goal_ids:
        report = reports_by_goal.get(goal_id)
        status = str(report.get("status")) if report is not None else "missing_report"
        statuses[goal_id] = status
        if status != "sufficient":
            incomplete.append(goal_id)
    return {
        "required": True,
        "sufficient": not incomplete,
        "planned_goal_ids": planned_goal_ids,
        "complete_goal_ids": [goal_id for goal_id in planned_goal_ids if goal_id not in set(incomplete)],
        "incomplete_goal_ids": incomplete,
        "latest_status_by_goal_id": statuses,
    }


def _planned_retrieval_goal_ids_from_recipe(recipe: TaskRecipe) -> list[str]:
    plan = recipe.metadata.get("task_execution_plan")
    if not isinstance(plan, dict):
        return []
    steps = plan.get("steps")
    if not isinstance(steps, list):
        return []
    goal_ids: list[str] = []
    for raw_step in steps:
        if not isinstance(raw_step, dict):
            continue
        if str(raw_step.get("status") or "") != "ready":
            continue
        if str(raw_step.get("tool_name") or "") != "retrieval.run":
            continue
        sequence = raw_step.get("sequence_index")
        sequence_id = sequence if isinstance(sequence, int) and sequence > 0 else 1_000_000
        metadata = raw_step.get("metadata")
        metadata = metadata if isinstance(metadata, dict) else {}
        capability_args = metadata.get("capability_args")
        capability_args = capability_args if isinstance(capability_args, dict) else {}
        payloads = _retrieval_payloads_from_capability_args(capability_args.get("retrieval.run"))
        if not payloads:
            continue
        total = len(payloads)
        for index, payload in enumerate(payloads, start=1):
            goal_id = payload.get("goal_id")
            if isinstance(goal_id, str) and goal_id:
                goal_ids.append(goal_id)
            else:
                goal_ids.append(f"goal-plan-{sequence_id}" if total == 1 else f"goal-plan-{sequence_id}-{index}")
    return _ordered_unique(goal_ids)


def _retrieval_payloads_from_capability_args(value: object) -> list[JsonObject]:
    if isinstance(value, dict):
        return [dict(value)]
    if isinstance(value, list):
        return [dict(item) for item in value if isinstance(item, dict)]
    return []


def _decision_missing_evidence(decision: TerminationDecision) -> list[str]:
    missing = _string_list(decision.diagnostics.get("evidence_missing"))
    return missing or ([decision.reason] if decision.reason else [])


def _seen_artifact_before(journal: JournalStore, *, task_id: str, record_id: str, artifact_id: str) -> bool:
    for record in journal.records(task_id=task_id):
        if record.record_id == record_id:
            return False
        if artifact_id in record.artifact_refs:
            return True
    return False


def _action_narrows_scope(data: JsonObject) -> bool:
    payload = data.get("payload")
    if not isinstance(payload, dict):
        return False
    for key in ("query", "path", "goal"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return True
    return False


def _strongest_signal(signals: list[ProgressSignal]) -> str:
    if not signals:
        return "none"
    return max(signals, key=lambda signal: signal.weight).signal_type


def _action_fingerprints(journal: JournalStore, *, task_id: str, run_id: str) -> list[tuple[str, str]]:
    values = []
    for record in journal.records(task_id=task_id, kind="action"):
        if record.run_id != run_id:
            continue
        key = str(record.data.get("name") or record.data.get("kind") or "")
        payload = record.data.get("payload", {})
        values.append((_hash({"key": key, "payload": payload}), record.record_id))
    return values


def _retrieval_queries(journal: JournalStore, *, task_id: str, run_id: str) -> list[tuple[str, str]]:
    values = []
    for record in journal.records(task_id=task_id, kind="retrieval_search_attempt"):
        if record.run_id != run_id:
            continue
        query = record.data.get("query")
        if isinstance(query, str):
            values.append((query.lower(), record.record_id))
    return values


def _file_paths(journal: JournalStore, *, task_id: str, run_id: str) -> list[tuple[str, str]]:
    values = []
    for record in journal.records(task_id=task_id, kind="observation"):
        if record.run_id != run_id:
            continue
        content = record.data.get("content")
        if isinstance(content, dict) and isinstance(content.get("path"), str):
            values.append((str(content["path"]).lower(), record.record_id))
    return values


def _observation_hashes(journal: JournalStore, *, task_id: str, run_id: str) -> list[tuple[str, str]]:
    return [
        (_hash(record.data), record.record_id)
        for record in journal.records(task_id=task_id, kind="observation")
        if record.run_id == run_id
    ]


def _missing_evidence_values(journal: JournalStore, *, task_id: str, run_id: str, latest: list[str]) -> list[tuple[str, str]]:
    if not latest:
        return []
    values = []
    for record in journal.records(task_id=task_id, kind="feedback"):
        if record.run_id != run_id:
            continue
        missing = record.data.get("missing_evidence")
        if isinstance(missing, list) and missing:
            values.append((_hash([str(item) for item in missing]), record.record_id))
    values.append((_hash([str(item) for item in latest]), "latest-feedback"))
    return values


def _failure_reasons(journal: JournalStore, *, task_id: str, run_id: str | None = None) -> list[str]:
    reasons = []
    for record in journal.records(task_id=task_id):
        if run_id is not None and record.run_id != run_id:
            continue
        reason = _failure_reason_from_record(record)
        if isinstance(reason, str) and reason:
            reasons.append(reason)
    return reasons


def _failure_reason_values(journal: JournalStore, *, task_id: str, run_id: str) -> list[tuple[str, str]]:
    values = []
    for record in journal.records(task_id=task_id):
        if record.run_id != run_id:
            continue
        reason = _failure_reason_from_record(record)
        if isinstance(reason, str) and reason:
            values.append((reason, record.record_id))
    return values


def _failure_reason_from_record(record) -> str | None:
    if record.kind == "agent_failure_report":
        reason = record.data.get("reason")
        return str(reason) if isinstance(reason, str) else None
    if record.kind == "termination_decision":
        decision = record.data.get("decision")
        if decision not in {"failure_report", "blocked"}:
            return None
        reason = record.data.get("reason")
        return str(reason) if isinstance(reason, str) else None
    if record.kind == "feedback":
        if record.data.get("status") not in {"failed", "blocked", "step_limit_exceeded"}:
            return None
        reason = record.data.get("stop_reason")
        return str(reason) if isinstance(reason, str) else None
    return None


def _repeat_for_values(
    values: list[tuple[str, str]],
    *,
    threshold: int,
    repeat_type: str,
) -> tuple[str, int, int, list[str]] | None:
    if threshold <= 1 or not values:
        return None
    latest_value = values[-1][0]
    refs = [ref for value, ref in values if value == latest_value]
    if len(refs) >= threshold:
        return repeat_type, len(refs), threshold, refs
    return None


def _recent_no_progress_count(journal: JournalStore, *, task_id: str, run_id: str) -> int:
    count = 0
    for record in reversed(journal.records(task_id=task_id, kind="progress_assessment")):
        if record.run_id != run_id:
            continue
        if record.data.get("made_progress") is False:
            count += 1
            continue
        break
    return count


def _latest_missing_evidence(journal: JournalStore, *, task_id: str, run_id: str | None = None) -> list[str]:
    for record in reversed(journal.records(task_id=task_id, kind="feedback")):
        if run_id is not None and record.run_id != run_id:
            continue
        missing = record.data.get("missing_evidence")
        if isinstance(missing, list):
            return [str(item) for item in missing]
    return []


def _dict_or_empty(value: object) -> JsonObject:
    return dict(value) if isinstance(value, dict) else {}


def _string_or_empty(value: object) -> str:
    return str(value) if isinstance(value, str) else ""


def _missing_source_authority(*, requirement: str, authority_summary: JsonObject) -> list[str]:
    if not requirement:
        return []
    primary = _int_or_zero(authority_summary.get("primary_source_count"))
    secondary = _int_or_zero(authority_summary.get("secondary_source_count"))
    if requirement == "primary" and primary <= 0:
        return ["source_authority:primary", "primary_source"]
    if requirement == "secondary_or_better" and primary + secondary <= 0:
        return ["source_authority:secondary_or_better", "secondary_or_better_source"]
    return []


def _int_or_zero(value: object) -> int:
    return value if isinstance(value, int) else 0


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if isinstance(item, str) and item]


def _hash(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _ordered_unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result
