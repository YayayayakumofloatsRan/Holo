from __future__ import annotations

import json
import math
import re
import time
import urllib.parse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Protocol

from kernel_v3.chat.contracts import ChatRuntimeResult
from kernel_v3.contracts import Contract, JsonObject, JsonValue
from kernel_v3.journal import JournalStore
from kernel_v3.retrieval import retrieval_behavior_benchmark
from kernel_v3.storage import safe_storage_id
from kernel_v3.substrate import Claim, EvidencePolicy, SlotFill, SlotFrame, SlotSpec, TransformPlan, VerificationGateResult


SENTINEL_GOLD_ANSWERS = {"INCORRECT_PREMISE", "NOT_AVAILABLE", "NOT ENOUGH INFORMATION"}
UNAVAILABLE_MARKERS = (
    "not available",
    "incorrect premise",
    "insufficient evidence",
    "not enough information",
    "cannot determine",
    "can't determine",
    "does not contain",
    "doesn't contain",
    "not present",
    "not directly available",
    "not available in the provided evidence",
    "not in the provided evidence",
    "no evidence",
    "无法确定",
    "证据不足",
    "不可得",
    "无法回答",
    "没有足够",
    "缺少",
)


class ChatRuntimeLike(Protocol):
    journal: JournalStore

    def receive(self, text: str, *, thread_id: str = "default") -> ChatRuntimeResult:
        ...


@dataclass(frozen=True, kw_only=True)
class FinanceBenchmarkItem(Contract):
    item_id: str
    question: str
    gold_answer: str | None = None
    numeric_value: float | None = None
    tolerance: float | None = None
    evidence_excerpt: str | None = None
    required_tools: list[str] = field(default_factory=list)
    category: str | None = None
    source: str | None = None
    workflow_type: str | None = None
    required_slots: list[str] = field(default_factory=list)
    evidence_policy: JsonObject = field(default_factory=dict)
    required_transforms: list[str] = field(default_factory=list)
    dealbreakers: list[str] = field(default_factory=list)
    expected_trace: list[str] = field(default_factory=list)
    failure_taxonomy: list[str] = field(default_factory=list)
    metadata: JsonObject = field(default_factory=dict)


@dataclass(frozen=True, kw_only=True)
class FinanceBenchmarkSplitSpec(Contract):
    split_id: str
    benchmark: str
    purpose: str
    offset: int
    limit: int | None
    expected_count: int | None
    description: str


@dataclass(frozen=True, kw_only=True)
class FinanceBenchmarkResult(Contract):
    item_id: str
    status: str
    question: str
    answer: str
    task_id: str | None
    run_id: str | None
    thread_id: str | None
    scorecard: JsonObject
    trace_metrics: JsonObject
    trace_refs: list[str]
    final_answer: JsonObject | None
    failure_report: JsonObject | None
    metadata: JsonObject = field(default_factory=dict)


@dataclass(frozen=True, kw_only=True)
class FinanceBenchmarkSummary(Contract):
    schema: str
    status: str
    item_count: int
    scored_count: int
    passed_count: int
    failed_count: int
    ungraded_count: int
    pass_rate: float
    answer_present_rate: float
    citation_present_rate: float
    numeric_accuracy: float | None
    adversarial_accuracy: float | None
    average_total_tokens: float
    average_duration_ms: float
    average_retrieval_runs: float
    average_query_repetition_rate: float
    calculator_used_rate: float
    average_calculator_calls: float
    formula_trace_present_rate: float
    average_formula_traces: float
    claim_ledger_present_rate: float
    compiled_task_program_present_rate: float
    average_compiled_evidence_specs: float
    average_compiled_transform_specs: float
    transform_plan_present_rate: float
    average_transform_plans: float
    slot_frame_present_rate: float
    average_missing_slots: float
    average_claims: float
    average_finance_facts: float
    workbench_decision_present_rate: float
    workbench_continue_rate: float | None
    workbench_sufficient_rate: float | None
    average_workbench_rescued_count: float
    average_workbench_actual_rescued_count: float
    average_workbench_rescue_blocked_count: float
    average_workbench_semantic_missing_slots: float
    numeric_verifier_pass_rate: float | None
    verifier_gate_pass_rate: float | None
    synthesis_gate_pass_rate: float | None
    synthesis_gate_repair_rate: float | None
    average_answer_numeric_support_rate: float | None
    citation_preservation_rate: float
    unsupported_numeric_claim_rate: float
    missing_slot_recovery_rate: float | None
    average_total_tokens_per_passed_item: float | None
    repeated_item_count: int
    repeatability_score: float | None
    workflow_type_counts: JsonObject
    finance_numeric_failure_reason_counts: JsonObject
    status_counts: JsonObject
    output_path: str | None = None
    dev_annotation_score: JsonObject | None = None
    benchmark_split: JsonObject = field(default_factory=dict)


FinanceBenchmarkResultCallback = Callable[[int, FinanceBenchmarkItem, FinanceBenchmarkResult], None]


FINANCEBENCH_DEBUG50_SPLIT = FinanceBenchmarkSplitSpec(
    split_id="financebench_debug50",
    benchmark="financebench",
    purpose="system_tuning_only",
    offset=0,
    limit=50,
    expected_count=50,
    description="FinanceBench public rows 0-49. Use only for system debugging and tuning.",
)
FINANCEBENCH_TEST100_SPLIT = FinanceBenchmarkSplitSpec(
    split_id="financebench_test100",
    benchmark="financebench",
    purpose="heldout_evaluation",
    offset=50,
    limit=100,
    expected_count=100,
    description="FinanceBench public rows 50-149. Use for held-out accuracy after the system is frozen.",
)
FINANCEBENCH_ALL150_SPLIT = FinanceBenchmarkSplitSpec(
    split_id="financebench_all150",
    benchmark="financebench",
    purpose="full_public_accounting",
    offset=0,
    limit=150,
    expected_count=150,
    description="All public FinanceBench rows. Report debug50 and test100 separately when using this for accounting.",
)

FINANCE_BENCHMARK_SPLITS: dict[str, FinanceBenchmarkSplitSpec] = {
    "financebench_debug50": FINANCEBENCH_DEBUG50_SPLIT,
    "fb_debug50": FINANCEBENCH_DEBUG50_SPLIT,
    "debug50": FINANCEBENCH_DEBUG50_SPLIT,
    "financebench_test100": FINANCEBENCH_TEST100_SPLIT,
    "financebench_holdout100": FINANCEBENCH_TEST100_SPLIT,
    "fb_test100": FINANCEBENCH_TEST100_SPLIT,
    "fb_holdout100": FINANCEBENCH_TEST100_SPLIT,
    "test100": FINANCEBENCH_TEST100_SPLIT,
    "holdout100": FINANCEBENCH_TEST100_SPLIT,
    "financebench_all150": FINANCEBENCH_ALL150_SPLIT,
    "fb_all150": FINANCEBENCH_ALL150_SPLIT,
    "all150": FINANCEBENCH_ALL150_SPLIT,
}


def resolve_finance_benchmark_split(split: str | None) -> FinanceBenchmarkSplitSpec | None:
    if split is None:
        return None
    normalized = str(split).strip().lower().replace("-", "_")
    if not normalized:
        return None
    spec = FINANCE_BENCHMARK_SPLITS.get(normalized)
    if spec is None:
        valid = ", ".join(sorted(FINANCE_BENCHMARK_SPLITS))
        raise ValueError(f"unknown finance benchmark split {split!r}; expected one of: {valid}")
    return spec


def load_finance_benchmark_items(path: Path | str, *, limit: int | None = None, offset: int = 0) -> list[FinanceBenchmarkItem]:
    records = _load_records(Path(path))
    items = [_item_from_record(record, index=index) for index, record in enumerate(records, start=1)]
    if offset > 0:
        items = items[offset:]
    if limit is not None:
        items = items[: max(0, int(limit))]
    return items


def score_finance_answer(
    item: FinanceBenchmarkItem,
    *,
    answer: str,
    final_answer: JsonObject | None = None,
    failure_report: JsonObject | None = None,
    trace_metrics: JsonObject | None = None,
) -> JsonObject:
    answer_text = str(answer or "")
    normalized_answer = _normalize_text(answer_text)
    gold = item.gold_answer or ""
    gold_sentinel = _gold_sentinel(gold)
    expected_numeric = item.numeric_value
    expected_tolerance = item.tolerance
    if expected_numeric is None and gold_sentinel:
        expected_numeric = _numeric_target_from_gold(gold)
        if expected_numeric is not None:
            expected_tolerance = max(abs(expected_numeric) * 0.01, 1.0)
    elif expected_numeric is None and gold:
        expected_numeric = _numeric_target_from_gold(gold)
        if expected_numeric is not None:
            expected_tolerance = max(abs(expected_numeric) * 0.01, 1.0)
    numeric = _score_numeric(answer_text, expected_numeric, expected_tolerance)
    gold_overlap = _token_overlap(gold, answer_text) if gold and not gold_sentinel else None
    gold_string_match = _normalize_text(gold) in normalized_answer if gold and not gold_sentinel else None
    citation_refs = _citation_refs(final_answer, answer_text=answer_text)
    citation_present = bool(citation_refs)
    unavailable_ack = _contains_any(normalized_answer, UNAVAILABLE_MARKERS)
    corrected_actual = gold_sentinel and bool(numeric["scored"]) and bool(numeric["passed"])
    source_grounded_actual = (
        gold_sentinel
        and not corrected_actual
        and bool(numeric.get("values"))
        and citation_present
        and _trace_supports_source_grounded_numeric_answer(trace_metrics or {})
    )
    answer_present = bool(normalized_answer.strip())

    scored = False
    passed = False
    reason = "ungraded_no_gold_signal"
    if gold_sentinel:
        scored = True
        passed = (unavailable_ack or corrected_actual or source_grounded_actual) and answer_present
        if corrected_actual:
            reason = "sentinel_actual_value_corrected"
        elif source_grounded_actual:
            reason = "sentinel_source_grounded_actual_answer"
        else:
            reason = "sentinel_answer_acknowledged" if passed else "sentinel_answer_not_acknowledged"
    elif numeric["scored"]:
        scored = True
        passed = bool(numeric["passed"])
        reason = "numeric_within_tolerance" if passed else "numeric_outside_tolerance"
    elif gold:
        scored = True
        passed = bool(gold_string_match) or (gold_overlap is not None and gold_overlap >= 0.55)
        reason = "gold_text_matched" if passed else "gold_text_not_matched"

    status = "passed" if scored and passed else "failed" if scored else "ungraded"
    if not answer_present:
        status = "failed" if scored else "ungraded"
        reason = "empty_answer"
    if failure_report is not None and final_answer is None and not gold_sentinel:
        status = "failed" if scored else "ungraded"
        reason = "failure_report_not_final_answer"

    return {
        "schema": "holo.kernel_v3.finance_benchmark_score.v1",
        "status": status,
        "scored": scored,
        "reason": reason,
        "answer_present": answer_present,
        "gold_sentinel": gold_sentinel,
        "unavailable_acknowledged": unavailable_ack,
        "corrected_actual_value": corrected_actual,
        "source_grounded_actual_value": source_grounded_actual,
        "gold_string_match": gold_string_match,
        "gold_token_overlap": gold_overlap,
        "numeric": numeric,
        "citation_present": citation_present,
        "citation_refs": citation_refs[:64],
        "failure_report_present": failure_report is not None,
        "trace_metrics": dict(trace_metrics or {}),
    }


def _trace_supports_source_grounded_numeric_answer(trace_metrics: JsonObject) -> bool:
    if trace_metrics.get("numeric_verifier_passed") is True:
        return True
    if trace_metrics.get("verifier_gate_passed") is True:
        return True
    if str(trace_metrics.get("numeric_verifier_status") or "").casefold() == "passed":
        return True
    if str(trace_metrics.get("verifier_gate_status") or "").casefold() == "passed":
        return True
    return False


def run_finance_benchmark(
    *,
    items: list[FinanceBenchmarkItem],
    runtime: ChatRuntimeLike,
    thread_prefix: str = "finance-bench",
    question_prefix: str = "",
    journal: JournalStore | None = None,
    result_callback: FinanceBenchmarkResultCallback | None = None,
) -> list[FinanceBenchmarkResult]:
    journal = journal or getattr(runtime, "journal", None)
    results: list[FinanceBenchmarkResult] = []
    for index, item in enumerate(items, start=1):
        thread_id = f"{safe_storage_id(thread_prefix)}-{index:04d}-{safe_storage_id(item.item_id)}"
        prompt = _benchmark_prompt(item, question_prefix=question_prefix)
        payload = runtime.receive(prompt, thread_id=thread_id)
        answer = _answer_from_chat_result(payload)
        _append_benchmark_provided_context_trace(journal, item=item, task_id=payload.task_id, run_id=payload.run_id)
        metrics = trace_metrics(journal, task_id=payload.task_id)
        scorecard = score_finance_answer(
            item,
            answer=answer,
            final_answer=payload.final_answer,
            failure_report=payload.failure_report,
            trace_metrics=metrics,
        )
        result = FinanceBenchmarkResult(
            item_id=item.item_id,
            status=str(scorecard["status"]),
            question=item.question,
            answer=answer,
            task_id=payload.task_id,
            run_id=payload.run_id,
            thread_id=payload.thread_id,
            scorecard=scorecard,
            trace_metrics=metrics,
            trace_refs=list(payload.trace_refs),
            final_answer=payload.final_answer,
            failure_report=payload.failure_report,
            metadata={
                "category": item.category,
                "source": item.source,
                "required_tools": list(item.required_tools),
                "workflow_type": item.workflow_type,
                "required_slots": list(item.required_slots),
                "evidence_policy": dict(item.evidence_policy),
                "required_transforms": list(item.required_transforms),
                "dealbreakers": list(item.dealbreakers),
                "expected_trace": list(item.expected_trace),
                "failure_taxonomy": list(item.failure_taxonomy),
            },
        )
        results.append(result)
        if journal is not None:
            journal.append(
                task_id=payload.task_id,
                run_id=payload.run_id or "finance-benchmark",
                step_id=None,
                kind="finance_benchmark_item_result",
                data=result.to_dict(),
                state_delta={"finance_benchmark_status": result.status, "finance_benchmark_item_id": item.item_id},
            )
        if result_callback is not None:
            result_callback(index, item, result)
    return results


def run_finance_benchmark_parallel(
    *,
    items: list[FinanceBenchmarkItem],
    runtime_factory: Callable[[int, FinanceBenchmarkItem], ChatRuntimeLike],
    max_workers: int,
    thread_prefix: str = "finance-bench",
    question_prefix: str = "",
    result_callback: FinanceBenchmarkResultCallback | None = None,
) -> list[FinanceBenchmarkResult]:
    if max_workers <= 1:
        results: list[FinanceBenchmarkResult] = []
        for index, item in enumerate(items, start=1):
            runtime = runtime_factory(index, item)
            results.extend(
                run_finance_benchmark(
                    items=[item],
                    runtime=runtime,
                    thread_prefix=thread_prefix,
                    question_prefix=question_prefix,
                    journal=getattr(runtime, "journal", None),
                    result_callback=result_callback,
                )
            )
        return results

    by_index: dict[int, FinanceBenchmarkResult] = {}
    with ThreadPoolExecutor(max_workers=max(1, int(max_workers))) as pool:
        futures = {
            pool.submit(
                _run_one_finance_benchmark_item,
                index,
                item,
                runtime_factory,
                thread_prefix,
                question_prefix,
            ): index
            for index, item in enumerate(items, start=1)
        }
        for future in as_completed(futures):
            index = futures[future]
            result = future.result()
            by_index[index] = result
            if result_callback is not None:
                result_callback(index, items[index - 1], result)
    return [by_index[index] for index in sorted(by_index)]


def score_finance_prediction_file(
    *,
    dataset_path: Path | str,
    predictions_path: Path | str,
    limit: int | None = None,
    offset: int = 0,
) -> list[FinanceBenchmarkResult]:
    items = load_finance_benchmark_items(dataset_path, limit=limit, offset=offset)
    predictions = _prediction_map(_load_records(Path(predictions_path)))
    results: list[FinanceBenchmarkResult] = []
    for item in items:
        prediction = predictions.get(item.item_id, {})
        answer = _coerce_text(
            _first_present(
                prediction,
                "answer",
                "prediction",
                "final_answer",
                "response",
                "output",
            )
        )
        final_answer = prediction.get("final_answer") if isinstance(prediction.get("final_answer"), dict) else None
        if final_answer is None:
            scorecard_payload = prediction.get("scorecard")
            if isinstance(scorecard_payload, dict) and isinstance(scorecard_payload.get("citation_refs"), list):
                final_answer = {"citation_refs": scorecard_payload.get("citation_refs")}
        trace_metrics_payload = prediction.get("trace_metrics") if isinstance(prediction.get("trace_metrics"), dict) else {}
        scorecard = score_finance_answer(
            item,
            answer=answer,
            final_answer=final_answer,
            failure_report=prediction.get("failure_report") if isinstance(prediction.get("failure_report"), dict) else None,
            trace_metrics=trace_metrics_payload,
        )
        results.append(
            FinanceBenchmarkResult(
                item_id=item.item_id,
                status=str(scorecard["status"]),
                question=item.question,
                answer=answer,
                task_id=_optional_str(prediction.get("task_id")),
                run_id=_optional_str(prediction.get("run_id")),
                thread_id=_optional_str(prediction.get("thread_id")),
                scorecard=scorecard,
                trace_metrics=dict(trace_metrics_payload),
                trace_refs=[str(ref) for ref in prediction.get("trace_refs", [])] if isinstance(prediction.get("trace_refs"), list) else [],
                final_answer=final_answer,
                failure_report=prediction.get("failure_report") if isinstance(prediction.get("failure_report"), dict) else None,
                metadata={
                    "source": "prediction_file",
                    "category": item.category,
                    "workflow_type": item.workflow_type,
                    "required_slots": list(item.required_slots),
                    "evidence_policy": dict(item.evidence_policy),
                    "required_transforms": list(item.required_transforms),
                    "dealbreakers": list(item.dealbreakers),
                    "expected_trace": list(item.expected_trace),
                    "failure_taxonomy": list(item.failure_taxonomy),
                },
            )
        )
    return results


def summarize_finance_benchmark(
    results: list[FinanceBenchmarkResult],
    *,
    output_path: Path | None = None,
    annotation_path: Path | str | None = None,
    benchmark_split: FinanceBenchmarkSplitSpec | JsonObject | None = None,
) -> FinanceBenchmarkSummary:
    status_counts = Counter(result.status for result in results)
    scored = [result for result in results if bool(result.scorecard.get("scored"))]
    numeric_scored = [
        result for result in results if isinstance(result.scorecard.get("numeric"), dict) and result.scorecard["numeric"].get("scored")
    ]
    adversarial_scored = [result for result in results if bool(result.scorecard.get("gold_sentinel"))]
    verifier_scored = [result for result in results if result.trace_metrics.get("numeric_verifier_status") in {"passed", "failed"}]
    gate_scored = [result for result in results if result.trace_metrics.get("verifier_gate_status") in {"passed", "failed"}]
    synthesis_gate_scored = [result for result in results if result.trace_metrics.get("synthesis_gate_status") in {"passed", "failed"}]
    synthesis_gate_repairable = [
        result for result in results
        if int(result.trace_metrics.get("synthesis_gate_attempt_count") or 0) > 1
        or result.trace_metrics.get("synthesis_gate_repaired") is True
    ]
    missing_slot_recovery_scored = [
        result for result in results
        if int(result.trace_metrics.get("missing_slot_transform_plan_count") or 0) > 0
    ]
    passed_token_values = [
        float(result.trace_metrics["total_tokens"])
        for result in results
        if result.status == "passed" and isinstance(result.trace_metrics.get("total_tokens"), (int, float))
    ]
    support_rates = [
        float(result.trace_metrics["answer_numeric_support_rate"])
        for result in results
        if isinstance(result.trace_metrics.get("answer_numeric_support_rate"), (int, float))
    ]
    numeric_failure_reasons = Counter(
        str(result.trace_metrics.get("finance_numeric_failure_reason"))
        for result in results
        if result.trace_metrics.get("finance_numeric_failure_reason") not in (None, "")
    )
    unsupported_numeric_count = sum(
        1
        for result in results
        if "unsupported_answer_number" in _string_list(result.trace_metrics.get("finance_numeric_failure_reasons"))
        or result.trace_metrics.get("finance_numeric_failure_reason") == "unsupported_answer_number"
    )
    workflow_type_counts = Counter(
        str(result.metadata.get("workflow_type") or result.metadata.get("category") or "unclassified")
        for result in results
    )
    repeated_item_count, repeatability_score = _repeatability_summary(results)
    return FinanceBenchmarkSummary(
        schema="holo.kernel_v3.finance_benchmark_summary.v1",
        status="ok",
        item_count=len(results),
        scored_count=len(scored),
        passed_count=status_counts.get("passed", 0),
        failed_count=status_counts.get("failed", 0),
        ungraded_count=status_counts.get("ungraded", 0),
        pass_rate=_rate(status_counts.get("passed", 0), len(scored)),
        answer_present_rate=_rate(_count_scorecard(results, "answer_present"), len(results)),
        citation_present_rate=_rate(_count_scorecard(results, "citation_present"), len(results)),
        numeric_accuracy=_rate(
            sum(1 for result in numeric_scored if result.scorecard["numeric"].get("passed")),
            len(numeric_scored),
        )
        if numeric_scored
        else None,
        adversarial_accuracy=_rate(
            sum(1 for result in adversarial_scored if result.status == "passed"),
            len(adversarial_scored),
        )
        if adversarial_scored
        else None,
        average_total_tokens=_average_metric(results, "total_tokens"),
        average_duration_ms=_average_metric(results, "processor_duration_ms"),
        average_retrieval_runs=_average_metric(results, "retrieval_run_count"),
        average_query_repetition_rate=_average_metric(results, "query_repetition_rate"),
        calculator_used_rate=_rate(sum(1 for result in results if int(result.trace_metrics.get("calculator_call_count") or 0) > 0), len(results)),
        average_calculator_calls=_average_metric(results, "calculator_call_count"),
        formula_trace_present_rate=_rate(sum(1 for result in results if int(result.trace_metrics.get("formula_trace_count") or 0) > 0), len(results)),
        average_formula_traces=_average_metric(results, "formula_trace_count"),
        claim_ledger_present_rate=_rate(sum(1 for result in results if bool(result.trace_metrics.get("claim_ledger_present"))), len(results)),
        compiled_task_program_present_rate=_rate(
            sum(1 for result in results if bool(result.trace_metrics.get("compiled_task_program_present"))),
            len(results),
        ),
        average_compiled_evidence_specs=_average_metric(results, "compiled_evidence_spec_count"),
        average_compiled_transform_specs=_average_metric(results, "compiled_transform_spec_count"),
        transform_plan_present_rate=_rate(sum(1 for result in results if int(result.trace_metrics.get("transform_plan_count") or 0) > 0), len(results)),
        average_transform_plans=_average_metric(results, "transform_plan_count"),
        slot_frame_present_rate=_rate(sum(1 for result in results if bool(result.trace_metrics.get("slot_frame_present"))), len(results)),
        average_missing_slots=_average_metric(results, "missing_slot_count"),
        average_claims=_average_metric(results, "claim_count"),
        average_finance_facts=_average_metric(results, "finance_fact_count"),
        workbench_decision_present_rate=_rate(
            sum(1 for result in results if bool(result.trace_metrics.get("workbench_decision_present"))),
            len(results),
        ),
        workbench_continue_rate=_rate(
            sum(1 for result in results if result.trace_metrics.get("workbench_decision") == "continue"),
            sum(1 for result in results if result.trace_metrics.get("workbench_decision")),
        )
        if any(result.trace_metrics.get("workbench_decision") for result in results)
        else None,
        workbench_sufficient_rate=_rate(
            sum(1 for result in results if result.trace_metrics.get("workbench_decision") == "sufficient"),
            sum(1 for result in results if result.trace_metrics.get("workbench_decision")),
        )
        if any(result.trace_metrics.get("workbench_decision") for result in results)
        else None,
        average_workbench_rescued_count=_average_metric(results, "workbench_rescued_count"),
        average_workbench_actual_rescued_count=_average_metric(results, "workbench_actual_rescued_count"),
        average_workbench_rescue_blocked_count=_average_metric(results, "workbench_rescue_blocked_count"),
        average_workbench_semantic_missing_slots=_average_metric(results, "workbench_semantic_missing_slot_count"),
        numeric_verifier_pass_rate=_rate(
            sum(1 for result in verifier_scored if result.trace_metrics.get("numeric_verifier_status") == "passed"),
            len(verifier_scored),
        )
        if verifier_scored
        else None,
        verifier_gate_pass_rate=_rate(
            sum(1 for result in gate_scored if result.trace_metrics.get("verifier_gate_status") == "passed"),
            len(gate_scored),
        )
        if gate_scored
        else None,
        synthesis_gate_pass_rate=_rate(
            sum(1 for result in synthesis_gate_scored if result.trace_metrics.get("synthesis_gate_status") == "passed"),
            len(synthesis_gate_scored),
        )
        if synthesis_gate_scored
        else None,
        synthesis_gate_repair_rate=_rate(
            sum(1 for result in synthesis_gate_repairable if result.trace_metrics.get("synthesis_gate_repaired") is True),
            len(synthesis_gate_repairable),
        )
        if synthesis_gate_repairable
        else None,
        average_answer_numeric_support_rate=_average(support_rates) if support_rates else None,
        citation_preservation_rate=_rate(_count_scorecard(results, "citation_present"), len(results)),
        unsupported_numeric_claim_rate=_rate(unsupported_numeric_count, len(results)),
        missing_slot_recovery_rate=_rate(
            sum(1 for result in missing_slot_recovery_scored if int(result.trace_metrics.get("missing_slot_count") or 0) == 0),
            len(missing_slot_recovery_scored),
        )
        if missing_slot_recovery_scored
        else None,
        average_total_tokens_per_passed_item=_average(passed_token_values) if passed_token_values else None,
        repeated_item_count=repeated_item_count,
        repeatability_score=repeatability_score,
        workflow_type_counts=dict(workflow_type_counts),
        finance_numeric_failure_reason_counts=dict(numeric_failure_reasons),
        status_counts=dict(status_counts),
        output_path=str(output_path) if output_path is not None else None,
        dev_annotation_score=score_finance_dev_annotations(results, annotation_path=annotation_path)
        if annotation_path is not None
        else None,
        benchmark_split=_benchmark_split_payload(benchmark_split),
    )


def write_finance_benchmark_outputs(
    results: list[FinanceBenchmarkResult],
    *,
    output_path: Path | str | None,
    summary_path: Path | str | None = None,
    annotation_path: Path | str | None = None,
    journal: JournalStore | None = None,
    benchmark_split: FinanceBenchmarkSplitSpec | JsonObject | None = None,
) -> FinanceBenchmarkSummary:
    output = Path(output_path) if output_path is not None else None
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            "\n".join(json.dumps(result.to_dict(), ensure_ascii=False, sort_keys=True) for result in results) + "\n",
            encoding="utf-8",
        )
    summary = summarize_finance_benchmark(
        results,
        output_path=output,
        annotation_path=annotation_path,
        benchmark_split=benchmark_split,
    )
    if summary_path is not None:
        path = Path(summary_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(summary.to_dict(), ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    if journal is not None:
        journal.append(
            task_id=None,
            run_id="finance-benchmark",
            step_id=None,
            kind="finance_benchmark_summary",
            data=summary.to_dict(),
            state_delta={"finance_benchmark_status": summary.status, "finance_benchmark_items": summary.item_count},
        )
    return summary


def score_finance_dev_annotations(
    results: list[FinanceBenchmarkResult],
    *,
    annotation_path: Path | str,
) -> JsonObject:
    annotations = _annotation_map(_load_records(Path(annotation_path)))
    item_scores: list[JsonObject] = []
    for result in results:
        annotation = annotations.get(result.item_id)
        if annotation is None:
            continue
        item_scores.append(_score_dev_annotation(result, annotation))
    behavior_scores = [float(item["behavior_score"]) for item in item_scores if isinstance(item.get("behavior_score"), (int, float))]
    numeric_scores = [float(item["numeric_score"]) for item in item_scores if isinstance(item.get("numeric_score"), (int, float))]
    substrate_scores = [float(item["substrate_score"]) for item in item_scores if isinstance(item.get("substrate_score"), (int, float))]
    workflow_scores = [float(item["workflow_score"]) for item in item_scores if isinstance(item.get("workflow_score"), (int, float))]
    behavior_score = _average(behavior_scores) if behavior_scores else None
    numeric_score = _average(numeric_scores) if numeric_scores else None
    substrate_score = _average(substrate_scores) if substrate_scores else None
    workflow_score = _average(workflow_scores) if workflow_scores else None
    component_scores = [
        score for score in (behavior_score, numeric_score, substrate_score, workflow_score) if isinstance(score, float)
    ]
    workflow_type_scores = _workflow_type_scores(item_scores)
    failure_reasons = Counter(
        str(reason)
        for item in item_scores
        for reason in item.get("failure_reasons", [])
        if isinstance(reason, str) and reason
    )
    return {
        "schema": "holo.kernel_v3.finance_dev_annotation_score.v1",
        "annotation_path": str(annotation_path),
        "annotated_item_count": len(annotations),
        "scored_item_count": len(item_scores),
        "behavior_score": behavior_score,
        "numeric_score": numeric_score,
        "substrate_score": substrate_score,
        "workflow_score": workflow_score,
        "workflow_type_scores": workflow_type_scores,
        "overall_score": _average(component_scores) if component_scores else None,
        "failure_reason_counts": dict(failure_reasons),
        "items": item_scores,
    }


def write_finance_dev_annotations_from_dataset(
    *,
    dataset_path: Path | str,
    annotation_path: Path | str,
) -> JsonObject:
    """Create post-run workflow annotations from a normalized benchmark dataset.

    The generated file is intended for `bench finance --dev-gold`; it preserves
    reference answers and numeric expectations only in the scoring sidecar, never
    in benchmark prompts.
    """
    items = load_finance_benchmark_items(dataset_path)
    annotations = [_dev_annotation_from_item(item) for item in items]
    output = Path(annotation_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        "\n".join(json.dumps(item, ensure_ascii=False, sort_keys=True) for item in annotations)
        + ("\n" if annotations else ""),
        encoding="utf-8",
    )
    return {
        "schema": "holo.kernel_v3.finance_dev_annotation_export.v1",
        "status": "ok",
        "dataset_path": str(dataset_path),
        "annotation_path": str(output),
        "item_count": len(annotations),
    }


def finance_benchmark_run_id() -> str:
    return "finbench-" + str(int(time.time() * 1000))


def trace_metrics(journal: JournalStore | None, *, task_id: str | None) -> JsonObject:
    if journal is None or task_id is None:
        return {}
    records = journal.records(task_id=task_id)
    processor_results = [record.data for record in records if record.kind == "processor_result"]
    actions = [record.data for record in records if record.kind == "action"]
    observations = [record.data for record in records if record.kind == "observation"]
    finance_ledgers = [record.data for record in records if record.kind == "finance_fact_ledger"]
    numeric_verifications = [record.data for record in records if record.kind == "finance_numeric_verification"]
    claim_ledgers = [record.data for record in records if record.kind == "claim_ledger"]
    slot_frames = [record.data for record in records if record.kind == "slot_frame"]
    transform_plans = [record.data for record in records if record.kind == "transform_plan"]
    compiled_programs = [record.data for record in records if record.kind == "compiled_task_program"]
    verifier_gates = [record.data for record in records if record.kind == "verifier_gate_result"]
    synthesis_gates = [record.data for record in records if record.kind == "synthesis_gate_result"]
    workbench_decisions = [record.data for record in records if record.kind == "retrieval_workbench_decision"]
    workbench_rescues = [record.data for record in records if record.kind == "retrieval_workbench_rescue"]
    retrieval_evidence_records = [record.data for record in records if record.kind == "retrieval_evidence"]
    retrieval_citation_records = [record.data for record in records if record.kind == "retrieval_citation"]
    retrieval = retrieval_behavior_benchmark(journal, task_id)
    total_tokens = 0
    duration_ms = 0
    processor_errors = 0
    for item in processor_results:
        usage = item.get("usage") if isinstance(item.get("usage"), dict) else {}
        total_tokens += _int_value(usage.get("total_tokens"))
        duration_ms += _int_value(item.get("duration_ms"))
        if item.get("status") != "ok":
            processor_errors += 1
    calculator_observations = [
        item for item in observations
        if item.get("source") == "tool:calculator.compute"
    ]
    formula_trace_ids = set()
    for item in calculator_observations:
        content = item.get("content") if isinstance(item.get("content"), dict) else {}
        trace = content.get("formula_trace") if isinstance(content.get("formula_trace"), dict) else {}
        formula_id = trace.get("formula_id")
        if isinstance(formula_id, str) and formula_id:
            formula_trace_ids.add(formula_id)
    latest_ledger = finance_ledgers[-1] if finance_ledgers else {}
    latest_claim_ledger = claim_ledgers[-1] if claim_ledgers else {}
    latest_slot_frame = slot_frames[-1] if slot_frames else {}
    latest_compiled_program = compiled_programs[-1] if compiled_programs else {}
    latest_verifier_gate = verifier_gates[-1] if verifier_gates else {}
    latest_synthesis_gate = synthesis_gates[-1] if synthesis_gates else {}
    latest_workbench = workbench_decisions[-1] if workbench_decisions else {}
    latest_workbench_rescue = workbench_rescues[-1] if workbench_rescues else {}
    synthesis_gate_statuses = [
        str(item.get("status"))
        for item in synthesis_gates
        if isinstance(item, dict) and isinstance(item.get("status"), str)
    ]
    latest_verification = numeric_verifications[-1] if numeric_verifications else {}
    latest_verification = latest_verification if isinstance(latest_verification, dict) else {}
    verification_diagnostics = latest_verification.get("diagnostics") if isinstance(latest_verification.get("diagnostics"), dict) else {}
    ledger_binding = latest_ledger.get("primary_source_numeric_binding") if isinstance(latest_ledger.get("primary_source_numeric_binding"), dict) else {}
    verifier_binding = (
        verification_diagnostics.get("primary_source_numeric_binding")
        if isinstance(verification_diagnostics.get("primary_source_numeric_binding"), dict)
        else {}
    )
    primary_binding = verifier_binding or ledger_binding
    answer_numeric_count = _int_value(verification_diagnostics.get("answer_numeric_count"))
    matched_values = latest_verification.get("matched_values") if isinstance(latest_verification.get("matched_values"), list) else []
    issue_codes = _finance_numeric_issue_codes(latest_verification)
    numeric_verifier_status = latest_verification.get("status") if isinstance(latest_verification.get("status"), str) else None
    verifier_gate_status = latest_verifier_gate.get("status") if isinstance(latest_verifier_gate.get("status"), str) else None
    verifier_gate_issues = latest_verifier_gate.get("issues") if isinstance(latest_verifier_gate.get("issues"), list) else []
    synthesis_gate_status = latest_synthesis_gate.get("status") if isinstance(latest_synthesis_gate.get("status"), str) else None
    synthesis_gate_issues = latest_synthesis_gate.get("issues") if isinstance(latest_synthesis_gate.get("issues"), list) else []
    answer_numeric_support_rate = _rate(len(matched_values), answer_numeric_count) if answer_numeric_count else None
    workbench_decision = latest_workbench.get("decision") if isinstance(latest_workbench.get("decision"), str) else None
    workbench_status = latest_workbench.get("status") if isinstance(latest_workbench.get("status"), str) else None
    workbench_missing_slots = latest_workbench.get("missing_slots") if isinstance(latest_workbench.get("missing_slots"), list) else []
    workbench_next_queries = latest_workbench.get("next_queries") if isinstance(latest_workbench.get("next_queries"), list) else []
    workbench_next_source_families = (
        latest_workbench.get("next_source_families")
        if isinstance(latest_workbench.get("next_source_families"), list)
        else []
    )
    source_uris = _ordered_unique([
        *_source_uris([*retrieval_evidence_records, *retrieval_citation_records]),
        *_claim_source_uris(claim_ledgers),
    ])
    source_hosts = _source_hosts(source_uris)
    target_document_urls = _target_document_trace_urls(latest_ledger)
    claim_citation_count = _claim_citation_count(claim_ledgers)
    finance_source_forms = _ordered_unique([*_finance_source_forms(finance_ledgers), *_claim_source_forms(claim_ledgers)])
    transform_methods = _transform_methods(transform_plans)
    return {
        "schema": "holo.kernel_v3.finance_trace_metrics.v1",
        "record_count": len(records),
        "processor_call_count": len(processor_results),
        "processor_error_count": processor_errors,
        "total_tokens": total_tokens,
        "processor_duration_ms": duration_ms,
        "action_count": len(actions),
        "retrieval_run_count": retrieval.get("retrieval_run_count", 0),
        "search_attempt_count": retrieval.get("search_attempt_count", 0),
        "query_count": retrieval.get("query_count", 0),
        "unique_query_count": retrieval.get("unique_query_count", 0),
        "query_repetition_rate": retrieval.get("query_repetition_rate", 0.0),
        "fetch_attempt_count": retrieval.get("fetch_attempt_count", 0),
        "fetch_success_rate": retrieval.get("fetch_success_rate", 0.0),
        "fetch_bytes": retrieval.get("fetch_bytes", 0),
        "downloaded_bytes": retrieval.get("downloaded_bytes", 0),
        "cache_hit_count": retrieval.get("cache_hit_count", 0),
        "download_budget_block_count": retrieval.get("download_budget_block_count", 0),
        "evidence_count": retrieval.get("evidence_count", 0),
        "citation_count": _int_value(retrieval.get("citation_count", 0)) + claim_citation_count,
        "retrieval_citation_count": retrieval.get("citation_count", 0),
        "claim_citation_count": claim_citation_count,
        "calculator_used": bool(calculator_observations),
        "calculator_call_count": len(calculator_observations),
        "formula_trace_present": bool(formula_trace_ids),
        "formula_trace_count": len(formula_trace_ids),
        "claim_ledger_present": bool(claim_ledgers),
        "claim_count": _int_value(latest_claim_ledger.get("claim_count")) if isinstance(latest_claim_ledger, dict) else 0,
        "compiled_task_program_present": bool(compiled_programs),
        "compiled_task_program_count": len(compiled_programs),
        "compiled_task_type": _compiled_task_type(latest_compiled_program),
        "compiled_evidence_spec_count": _compiled_list_count(latest_compiled_program, "evidence_specs"),
        "compiled_transform_spec_count": _compiled_list_count(latest_compiled_program, "transform_specs"),
        "compiled_missing_slots": _compiled_missing_slots(latest_compiled_program),
        "transform_plan_present": bool(transform_plans),
        "transform_plan_count": len(transform_plans),
        "transform_methods": transform_methods[:32],
        "ready_transform_plan_count": sum(1 for item in transform_plans if item.get("status") == "ready"),
        "missing_slot_transform_plan_count": sum(1 for item in transform_plans if item.get("status") == "missing_slots"),
        "slot_frame_present": bool(slot_frames),
        "slot_frame_task_type": latest_slot_frame.get("task_type") if isinstance(latest_slot_frame, dict) else None,
        "missing_slot_count": len(latest_slot_frame.get("missing_slots") or []) if isinstance(latest_slot_frame, dict) else 0,
        "missing_slots": latest_slot_frame.get("missing_slots") if isinstance(latest_slot_frame, dict) else [],
        "finance_fact_count": _int_value(latest_ledger.get("fact_count")) if isinstance(latest_ledger, dict) else 0,
        "target_document_binding_present": bool(
            isinstance(latest_ledger, dict) and isinstance(latest_ledger.get("target_document_binding"), dict) and latest_ledger.get("target_document_binding")
        ),
        "primary_source_numeric_binding_status": primary_binding.get("status") if isinstance(primary_binding.get("status"), str) else None,
        "primary_source_numeric_binding_selected_count": _int_value(primary_binding.get("selected_count")) if isinstance(primary_binding, dict) else 0,
        "primary_source_numeric_binding_rejected_count": _int_value(primary_binding.get("rejected_count")) if isinstance(primary_binding, dict) else 0,
        "primary_source_numeric_binding_selected_fact_ids": primary_binding.get("selected_fact_ids")[:16]
        if isinstance(primary_binding.get("selected_fact_ids"), list)
        else [],
        "workbench_decision_present": bool(workbench_decisions),
        "workbench_status": workbench_status,
        "workbench_decision": workbench_decision,
        "workbench_rescued_count": len(latest_workbench.get("rescued_evidence_ids") or []) if isinstance(latest_workbench, dict) else 0,
        "workbench_actual_rescued_count": _int_value(latest_workbench_rescue.get("rescued_count")) if isinstance(latest_workbench_rescue, dict) else 0,
        "workbench_rescue_blocked_count": _int_value(latest_workbench_rescue.get("blocked_count")) if isinstance(latest_workbench_rescue, dict) else 0,
        "workbench_semantic_missing_slot_count": len(workbench_missing_slots),
        "workbench_semantic_missing_slots": workbench_missing_slots[:32],
        "workbench_next_queries": workbench_next_queries[:8],
        "workbench_next_source_families": workbench_next_source_families[:12],
        "numeric_verifier_status": numeric_verifier_status,
        "numeric_verifier_passed": numeric_verifier_status == "passed" if numeric_verifier_status else None,
        "numeric_verifier_pass_rate": 1.0 if numeric_verifier_status == "passed" else 0.0 if numeric_verifier_status == "failed" else None,
        "verifier_gate_status": verifier_gate_status,
        "verifier_gate_passed": verifier_gate_status == "passed" if verifier_gate_status else None,
        "verifier_gate_issue_count": len(verifier_gate_issues),
        "synthesis_gate_status": synthesis_gate_status,
        "synthesis_gate_passed": synthesis_gate_status == "passed" if synthesis_gate_status else None,
        "synthesis_gate_issue_count": len(synthesis_gate_issues),
        "synthesis_gate_attempt_count": len(synthesis_gates),
        "synthesis_gate_statuses": synthesis_gate_statuses[:16],
        "synthesis_gate_repaired": "failed" in synthesis_gate_statuses and synthesis_gate_status == "passed",
        "answer_numeric_support_rate": answer_numeric_support_rate,
        "finance_numeric_failure_reason": issue_codes[0] if issue_codes else None,
        "finance_numeric_failure_reasons": issue_codes,
        "source_hosts": source_hosts[:64],
        "source_uris": source_uris[:64],
        "target_document_source_urls": target_document_urls[:16],
        "finance_source_forms": finance_source_forms[:64],
        "final_answer_chars": retrieval.get("final_answer_chars", 0),
        "latest_failure_mode": retrieval.get("latest_failure_mode"),
        "latest_next_strategy_hint": retrieval.get("latest_next_strategy_hint"),
    }


def _finance_numeric_issue_codes(verification: JsonObject) -> list[str]:
    issues = verification.get("issues") if isinstance(verification.get("issues"), list) else []
    codes: list[str] = []
    for issue in issues:
        if not isinstance(issue, dict):
            continue
        code = issue.get("code")
        if isinstance(code, str) and code:
            codes.append(code)
    return list(dict.fromkeys(codes))


def _annotation_map(records: list[JsonObject]) -> dict[str, JsonObject]:
    mapped: dict[str, JsonObject] = {}
    for index, record in enumerate(records, start=1):
        item_id = _coerce_text(_first_present(record, "item_id", "id", "question_id", "benchmark_id", "qid")) or f"item-{index}"
        mapped[item_id] = dict(record)
    return mapped


def _score_dev_annotation(result: FinanceBenchmarkResult, annotation: JsonObject) -> JsonObject:
    answer = result.answer or ""
    haystack = _annotation_haystack(result)
    expected_contains = _string_list(annotation.get("expected_answer_contains"))
    contains_hits = [item for item in expected_contains if _expected_contains_met(answer, item)]
    numeric_expectations = _expected_numeric_annotations(annotation.get("expected_numeric"))
    numeric_matches = [_score_expected_numeric(answer, expectation) for expectation in numeric_expectations]
    required_trace = _ordered_unique([*_string_list(annotation.get("required_trace")), *_string_list(annotation.get("expected_trace"))])
    trace_hits = [name for name in required_trace if _trace_requirement_met(name, result)]
    required_sources = _string_list(annotation.get("required_sources"))
    required_source_urls = _string_list(annotation.get("required_source_urls"))
    evidence_policy = _json_object_value(annotation.get("evidence_policy"))
    required_source_families = _string_list(evidence_policy.get("required_source_families"))
    required_terms = _string_list(evidence_policy.get("required_terms"))
    forbidden_source_families = _string_list(evidence_policy.get("forbidden_source_families"))
    source_url_hits = [url for url in required_source_urls if _source_url_requirement_met(url, result, haystack=haystack)]
    source_hits = [
        name
        for name in required_sources
        if _source_requirement_met(name, result, haystack=haystack)
        or _source_requirement_met_by_required_url(name, required_source_urls=required_source_urls, source_url_hits=source_url_hits)
    ]
    source_family_hits = [name for name in required_source_families if _source_requirement_met(name, result, haystack=haystack)]
    required_term_hits = [term for term in required_terms if _evidence_term_met(term, result, haystack=haystack)]
    forbidden_source_hits = [name for name in forbidden_source_families if _source_requirement_met(name, result, haystack=haystack)]
    required_slots = _string_list(annotation.get("required_slots"))
    slot_hits = [name for name in required_slots if _slot_requirement_met(name, result)]
    required_transforms = _string_list(annotation.get("required_transforms"))
    transform_hits = [name for name in required_transforms if _transform_requirement_met(name, result, haystack=haystack)]
    dealbreakers = _string_list(annotation.get("dealbreakers"))
    dealbreaker_matches = [_score_dealbreaker(name, result, haystack=haystack) for name in dealbreakers]
    dealbreaker_hits = [item for item in dealbreaker_matches if item.get("passed") is True]
    behavior_denominator = len(expected_contains) + len(required_sources) + len(required_source_urls)
    behavior_numerator = len(contains_hits) + len(source_hits) + len(source_url_hits)
    numeric_denominator = len(numeric_matches)
    numeric_numerator = sum(1 for item in numeric_matches if item.get("passed") is True)
    substrate_denominator = len(required_trace)
    substrate_numerator = len(trace_hits)
    workflow_denominator = (
        len(required_slots)
        + len(required_transforms)
        + len(required_source_families)
        + len(required_terms)
        + len(dealbreakers)
    )
    workflow_numerator = (
        len(slot_hits)
        + len(transform_hits)
        + len(source_family_hits)
        + len(required_term_hits)
        + len(dealbreaker_hits)
    )
    failure_reasons: list[str] = []
    if len(contains_hits) < len(expected_contains):
        failure_reasons.append("expected_answer_content_missing")
    if len(source_hits) < len(required_sources):
        failure_reasons.append("required_source_missing")
    if len(source_url_hits) < len(required_source_urls):
        failure_reasons.append("required_source_url_missing")
    if numeric_denominator and numeric_numerator < numeric_denominator:
        failure_reasons.append("expected_numeric_mismatch")
    if substrate_denominator and substrate_numerator < substrate_denominator:
        failure_reasons.append("required_trace_missing")
    if required_slots and len(slot_hits) < len(required_slots):
        failure_reasons.append("required_slot_missing")
    if required_transforms and len(transform_hits) < len(required_transforms):
        failure_reasons.append("required_transform_missing")
    if required_source_families and len(source_family_hits) < len(required_source_families):
        failure_reasons.append("required_source_family_missing")
    if required_terms and len(required_term_hits) < len(required_terms):
        failure_reasons.append("required_evidence_term_missing")
    if forbidden_source_hits:
        failure_reasons.append("forbidden_source_family_present")
    if dealbreaker_matches and len(dealbreaker_hits) < len(dealbreaker_matches):
        failure_reasons.append("dealbreaker_failed")
    return {
        "item_id": result.item_id,
        "workflow_type": annotation.get("workflow_type"),
        "behavior_score": _rate(behavior_numerator, behavior_denominator) if behavior_denominator else None,
        "numeric_score": _rate(numeric_numerator, numeric_denominator) if numeric_denominator else None,
        "substrate_score": _rate(substrate_numerator, substrate_denominator) if substrate_denominator else None,
        "workflow_score": _rate(workflow_numerator, workflow_denominator) if workflow_denominator else None,
        "expected_contains_count": len(expected_contains),
        "expected_contains_hit_count": len(contains_hits),
        "expected_numeric_count": len(numeric_expectations),
        "expected_numeric_hit_count": numeric_numerator,
        "required_trace_count": len(required_trace),
        "required_trace_hit_count": len(trace_hits),
        "required_source_count": len(required_sources),
        "required_source_hit_count": len(source_hits),
        "required_source_url_count": len(required_source_urls),
        "required_source_url_hit_count": len(source_url_hits),
        "required_slot_count": len(required_slots),
        "required_slot_hit_count": len(slot_hits),
        "required_transform_count": len(required_transforms),
        "required_transform_hit_count": len(transform_hits),
        "required_source_family_count": len(required_source_families),
        "required_source_family_hit_count": len(source_family_hits),
        "required_evidence_term_count": len(required_terms),
        "required_evidence_term_hit_count": len(required_term_hits),
        "dealbreaker_count": len(dealbreakers),
        "dealbreaker_hit_count": len(dealbreaker_hits),
        "dealbreaker_matches": dealbreaker_matches,
        "numeric_matches": numeric_matches,
        "missing_trace": [name for name in required_trace if name not in trace_hits],
        "missing_sources": [name for name in required_sources if name not in source_hits],
        "missing_source_urls": [url for url in required_source_urls if url not in source_url_hits],
        "missing_slots": [name for name in required_slots if name not in slot_hits],
        "missing_transforms": [name for name in required_transforms if name not in transform_hits],
        "missing_source_families": [name for name in required_source_families if name not in source_family_hits],
        "missing_evidence_terms": [name for name in required_terms if name not in required_term_hits],
        "forbidden_source_hits": forbidden_source_hits,
        "failure_reasons": failure_reasons,
    }


def _dev_annotation_from_item(item: FinanceBenchmarkItem) -> JsonObject:
    metadata = dict(item.metadata or {})
    annotation: JsonObject = {
        "item_id": item.item_id,
        "workflow_type": item.workflow_type or metadata.get("workflow_type") or item.category,
        "required_slots": list(item.required_slots),
        "evidence_policy": dict(item.evidence_policy),
        "required_transforms": list(item.required_transforms),
        "dealbreakers": list(item.dealbreakers),
        "expected_trace": list(item.expected_trace),
        "failure_taxonomy": list(item.failure_taxonomy),
        "source": item.source,
        "category": item.category,
        "gold_policy": "scoring_only_not_prompted",
    }
    required_sources = _annotation_required_sources(item)
    if required_sources:
        annotation["required_sources"] = required_sources
    required_source_urls = _annotation_required_source_urls(item)
    if required_source_urls:
        annotation["required_source_urls"] = required_source_urls
    expected_numeric = _numeric_expectations_from_gold(item.gold_answer)
    if expected_numeric:
        annotation["expected_numeric"] = expected_numeric
    expected_contains = _annotation_expected_contains(item)
    if expected_contains:
        annotation["expected_answer_contains"] = expected_contains
    return {key: value for key, value in annotation.items() if value not in (None, [], {})}


def _annotation_required_sources(item: FinanceBenchmarkItem) -> list[str]:
    sources: list[str] = []
    refs = item.metadata.get("source_refs") if isinstance(item.metadata.get("source_refs"), list) else []
    for ref in refs:
        if not isinstance(ref, dict):
            continue
        doc_type = _coerce_text(ref.get("doc_type"))
        if doc_type:
            sources.append(doc_type.lower())
        url = _coerce_text(ref.get("url"))
        if url:
            host = urllib.parse.urlparse(url).hostname
            if host:
                sources.append(host.lower())
    policy = item.evidence_policy if isinstance(item.evidence_policy, dict) else {}
    for family in _string_list(policy.get("required_source_families")):
        if family:
            sources.append(family)
    return _ordered_unique(sources)


def _annotation_required_source_urls(item: FinanceBenchmarkItem) -> list[str]:
    urls: list[str] = []
    refs = item.metadata.get("source_refs") if isinstance(item.metadata.get("source_refs"), list) else []
    for ref in refs:
        if not isinstance(ref, dict):
            continue
        url = _coerce_text(ref.get("url"))
        if url:
            urls.append(url)
    for key in ("doc_link", "source_url"):
        value = _coerce_text(item.metadata.get(key)) if isinstance(item.metadata, dict) else None
        if value:
            urls.append(value)
    return _ordered_unique(urls)


def _annotation_expected_contains(item: FinanceBenchmarkItem) -> list[str]:
    if not isinstance(item.metadata, dict):
        return []
    return _ordered_unique(_string_list(item.metadata.get("expected_answer_contains")))


def _numeric_expectations_from_gold(gold: str | None) -> list[JsonObject]:
    if not gold:
        return []
    expectations: list[JsonObject] = []
    seen: set[float] = set()
    for candidate in _extract_numeric_candidates(gold):
        value = float(candidate["value"])
        if _looks_like_year(value):
            continue
        if value in seen:
            continue
        seen.add(value)
        expectations.append(
            {
                "name": f"gold_numeric_{len(expectations) + 1}",
                "value": value,
                "tolerance": max(abs(value) * 0.01, 1.0),
            }
        )
        if len(expectations) >= 8:
            break
    return expectations


def _expected_contains_met(answer: str, expected: str) -> bool:
    normalized_answer = answer.casefold()
    normalized_expected = expected.casefold()
    if normalized_expected in normalized_answer:
        return True
    for alias in _expected_contains_aliases(normalized_expected):
        if alias in normalized_answer:
            return True
    return False


def _expected_contains_aliases(expected: str) -> tuple[str, ...]:
    aliases = {
        "days": ("天", "日", "days inventory outstanding", "dio"),
        "dio": ("库存周转天数", "days inventory outstanding"),
        "bridge": ("桥接", "调节", "调整"),
        "add": ("加回", "add-back", "addback"),
        "multiple": ("倍数",),
        "enterprise value": ("企业价值", "ev"),
        "assumption": ("假设",),
        "return": ("回报", "收益"),
        "formula": ("公式",),
        "period": ("期间", "周期"),
        "goodwill": ("商誉",),
    }
    return aliases.get(expected, ())


def _workflow_type_scores(item_scores: list[JsonObject]) -> JsonObject:
    buckets: dict[str, list[float]] = {}
    for item in item_scores:
        workflow_type = str(item.get("workflow_type") or "unclassified")
        score = item.get("workflow_score")
        if not isinstance(score, (int, float)):
            continue
        buckets.setdefault(workflow_type, []).append(float(score))
    return {
        workflow_type: {
            "item_count": len(scores),
            "workflow_score": _average(scores),
        }
        for workflow_type, scores in sorted(buckets.items())
    }


def _source_requirement_met(name: str, result: FinanceBenchmarkResult, *, haystack: str) -> bool:
    normalized = name.strip().casefold()
    if not normalized:
        return False
    if _looks_like_url_requirement(normalized):
        return _source_url_requirement_met(name, result, haystack=haystack)
    metrics = result.trace_metrics
    if normalized in {"provided_evidence_or_company_filing", "benchmark_evidence_or_primary_filing"}:
        return (
            bool(result.scorecard.get("citation_present"))
            or _int_value(metrics.get("citation_count")) > 0
            or _int_value(metrics.get("evidence_count")) > 0
            or "provided evidence" in haystack.casefold()
        )
    hosts = [str(item).casefold() for item in metrics.get("source_hosts", [])] if isinstance(metrics.get("source_hosts"), list) else []
    forms = [str(item).casefold() for item in metrics.get("finance_source_forms", [])] if isinstance(metrics.get("finance_source_forms"), list) else []
    source_text = " ".join([haystack.casefold(), *hosts, *forms])
    if normalized in hosts or any(host.endswith(f".{normalized}") for host in hosts):
        return True
    if _looks_like_host_requirement(normalized):
        return _source_host_requirement_met(normalized, result, haystack=haystack)
    aliases = {
        "sec": ("sec.gov", "www.sec.gov", "sec filing", "regulatory_filing"),
        "sec.gov": ("sec.gov", "www.sec.gov"),
        "sec_filings": ("sec.gov", "www.sec.gov", "10-k", "10k", "10-q", "10q", "8-k", "8k"),
        "companyfacts": ("companyfacts", "xbrl", "data.sec.gov"),
        "10-k": ("10-k", "form 10-k"),
        "10k": ("10-k", "10k", "form 10-k"),
        "10-q": ("10-q", "form 10-q"),
        "10q": ("10-q", "10q", "form 10-q"),
        "8-k": ("8-k", "form 8-k"),
        "8k": ("8-k", "8k", "form 8-k"),
        "ex-99": ("ex-99", "exhibit 99", "99.1"),
        "market_data": ("market", "stock price", "market cap", "enterprise value", "yahoo", "google finance"),
        "regulatory_filing": ("sec.gov", "10-k", "10-q", "8-k", "6-k"),
        "company_filing": ("sec.gov", "10-k", "10k", "10-q", "10q", "8-k", "8k", "6-k", "6k", "annual report", "quarterly report"),
        "primary_filing": ("sec.gov", "10-k", "10k", "10-q", "10q", "8-k", "8k", "6-k", "6k", "annual report", "quarterly report"),
        "provided_evidence_context": ("provided evidence", "benchmark-provided evidence", "provided_evidence_context"),
        "provided_report_context": (
            "provided_report_context",
            "benchmark:finqa",
            "finqasite.github.io",
            "pre_text",
            "post_text",
            "table",
            "context_table_or_text",
        ),
    }
    candidates = aliases.get(normalized, (normalized,))
    return any(candidate in source_text for candidate in candidates)


def _source_url_requirement_met(url: str, result: FinanceBenchmarkResult, *, haystack: str) -> bool:
    normalized_url = url.strip().casefold()
    if not normalized_url:
        return False
    observed = _result_source_urls(result)
    if any(normalized_url == item.casefold().rstrip("/") for item in observed):
        return True
    required_accession = _sec_accession_key(normalized_url)
    if not required_accession:
        return False
    if any(_sec_accession_key(item) == required_accession for item in observed):
        return True
    return _structured_sec_primary_binding_satisfies_required_url(url, result)


def _structured_sec_primary_binding_satisfies_required_url(url: str, result: FinanceBenchmarkResult) -> bool:
    metrics = result.trace_metrics if isinstance(result.trace_metrics, dict) else {}
    if metrics.get("primary_source_numeric_binding_status") != "selected":
        return False
    selected_count = metrics.get("primary_source_numeric_binding_selected_count")
    if isinstance(selected_count, (int, float)) and selected_count <= 0:
        return False
    required_accession = _sec_accession_key(url)
    if not required_accession:
        return False
    target_urls = _result_target_document_urls(result)
    if not any(_sec_accession_key(target_url) == required_accession for target_url in target_urls):
        return False
    source_hosts = {str(host).casefold() for host in metrics.get("source_hosts", []) if isinstance(host, str)}
    if not source_hosts.intersection({"data.sec.gov", "sec.gov", "www.sec.gov"}):
        return False
    observed = _result_source_urls(result)
    return any("data.sec.gov/api/xbrl/companyfacts/" in item.casefold() or "sec.gov" in item.casefold() for item in observed)


def _source_requirement_met_by_required_url(name: str, *, required_source_urls: list[str], source_url_hits: list[str]) -> bool:
    normalized = name.strip().casefold()
    if not _looks_like_host_requirement(normalized):
        return False
    hit_set = {url.casefold() for url in source_url_hits}
    for url in required_source_urls:
        parsed = urllib.parse.urlparse(url)
        host = (parsed.hostname or "").casefold()
        if host == normalized and url.casefold() in hit_set:
            return True
    return False


def _source_host_requirement_met(host: str, result: FinanceBenchmarkResult, *, haystack: str) -> bool:
    target_urls = _result_target_document_urls(result)
    if not any((urllib.parse.urlparse(url).hostname or "").casefold() == host for url in target_urls):
        return False
    target_accessions = {_sec_accession_key(url) for url in target_urls}
    target_accessions.discard("")
    if not target_accessions:
        return False
    observed = _result_source_urls(result)
    return any(_sec_accession_key(url) in target_accessions for url in observed)


def _looks_like_url_requirement(value: str) -> bool:
    parsed = urllib.parse.urlparse(value)
    return bool(parsed.scheme and parsed.netloc)


def _looks_like_host_requirement(value: str) -> bool:
    if "/" in value or " " in value:
        return False
    return "." in value


def _result_source_urls(result: FinanceBenchmarkResult) -> list[str]:
    metrics = result.trace_metrics if isinstance(result.trace_metrics, dict) else {}
    values = metrics.get("source_uris") if isinstance(metrics.get("source_uris"), list) else []
    urls = [str(value).rstrip("/") for value in values if isinstance(value, str) and _looks_like_url_requirement(value.casefold())]
    return _ordered_unique(urls)


def _result_target_document_urls(result: FinanceBenchmarkResult) -> list[str]:
    metrics = result.trace_metrics if isinstance(result.trace_metrics, dict) else {}
    values = metrics.get("target_document_source_urls") if isinstance(metrics.get("target_document_source_urls"), list) else []
    urls = [str(value).rstrip("/") for value in values if isinstance(value, str) and _looks_like_url_requirement(value.casefold())]
    return _ordered_unique(urls)


def _sec_accession_key(value: str) -> str:
    text = str(value or "")
    match = re.search(r"\b(\d{10})-?(\d{2})-?(\d{6})\b", text)
    if match:
        return "".join(match.groups())
    match = re.search(r"/Archives/edgar/data/\d+/(\d{18})(?:/|$)", text, flags=re.IGNORECASE)
    if match:
        return match.group(1)
    return ""


def _evidence_term_met(term: str, result: FinanceBenchmarkResult, *, haystack: str) -> bool:
    normalized = _norm_key(term)
    if not normalized:
        return False
    if normalized in {"context_table_or_text", "provided_context", "provided_report_context"}:
        source_hosts = result.trace_metrics.get("source_hosts") if isinstance(result.trace_metrics.get("source_hosts"), list) else []
        return bool(result.trace_metrics.get("claim_ledger_present")) and (
            "benchmark:finqa" in json.dumps(result.trace_metrics, ensure_ascii=False).casefold()
            or "provided_report_context" in haystack.casefold()
            or "finqasite.github.io" in {str(host).casefold() for host in source_hosts}
        )
    return term.casefold() in haystack.casefold()


def _slot_requirement_met(name: str, result: FinanceBenchmarkResult) -> bool:
    normalized = _norm_key(name)
    if not normalized:
        return False
    metrics = result.trace_metrics
    if not metrics.get("slot_frame_present"):
        return False
    missing_slots = metrics.get("missing_slots") if isinstance(metrics.get("missing_slots"), list) else []
    normalized_missing = {_norm_key(str(item)) for item in missing_slots}
    return normalized not in normalized_missing


def _transform_requirement_met(name: str, result: FinanceBenchmarkResult, *, haystack: str) -> bool:
    normalized = _norm_key(name)
    if not normalized:
        return False
    metrics = result.trace_metrics
    methods = metrics.get("transform_methods") if isinstance(metrics.get("transform_methods"), list) else []
    normalized_methods = [_norm_key(str(item)) for item in methods]
    if any(normalized in method or method in normalized for method in normalized_methods if method):
        return True
    aliases = {
        "dio": ("days_inventory_outstanding", "inventory_efficiency"),
        "difference": ("compare", "spread", "delta"),
        "adjusted_ebitda_bridge": ("adjusted_ebitda", "reconciliation", "bridge"),
        "addback_trend": ("addback", "add_back", "trend"),
        "ev_revenue": ("enterprise_value_revenue", "transaction_multiple", "ev_to_revenue"),
        "ev_ebitda": ("enterprise_value_ebitda", "valuation_multiple", "multiple"),
        "fixed_charge_coverage": ("coverage_ratio", "fixed_charge"),
        "dcf": ("discounted_cash_flow", "valuation_model"),
        "lbo": ("leveraged_buyout", "return_model"),
        "mlr_rebate": ("medical_loss_ratio", "regulatory_ratio"),
        "purchase_price_allocation": ("ppa", "purchase_accounting"),
    }
    candidates = (normalized, *aliases.get(normalized, ()))
    haystack_norm = _norm_key(haystack)
    if any(candidate and candidate in haystack_norm for candidate in candidates):
        return True
    return normalized in {"assumption_separation", "limitation"} and bool(metrics.get("synthesis_gate_status"))


def _score_dealbreaker(name: str, result: FinanceBenchmarkResult, *, haystack: str) -> JsonObject:
    normalized = _norm_key(name)
    metrics = result.trace_metrics
    passed = False
    if normalized in {"citation_required", "has_citation", "cite_sources"}:
        passed = bool(result.scorecard.get("citation_present"))
    elif normalized in {"calculator_trace_required", "calculator_required"}:
        passed = _int_value(metrics.get("calculator_call_count")) > 0 and _int_value(metrics.get("formula_trace_count")) > 0
    elif normalized in {"verifier_gate_pass_required", "verifier_required"}:
        passed = metrics.get("verifier_gate_status") == "passed"
    elif normalized in {"synthesis_gate_pass_required", "no_unsupported_numeric_claims"}:
        passed = metrics.get("synthesis_gate_status") == "passed" or metrics.get("finance_numeric_failure_reason") != "unsupported_answer_number"
    elif normalized in {"no_missing_slots", "slots_filled"}:
        passed = bool(metrics.get("slot_frame_present")) and _int_value(metrics.get("missing_slot_count")) == 0
    elif normalized in {"source_required", "source_family_required"}:
        passed = bool(result.scorecard.get("citation_present")) or _int_value(metrics.get("citation_count")) > 0
    elif normalized in {"assumptions_labeled", "facts_vs_assumptions_separated"}:
        passed = "assumption" in haystack.casefold() or "假设" in haystack
    elif normalized in {"failure_diagnostic_required", "diagnostic_failure"}:
        passed = bool(metrics.get("latest_failure_mode") or metrics.get("finance_numeric_failure_reason") or result.failure_report)
    else:
        passed = name.casefold() in haystack.casefold()
    return {"name": name, "passed": passed}


def _annotation_haystack(result: FinanceBenchmarkResult) -> str:
    parts: list[str] = [result.answer, json.dumps(result.trace_metrics, ensure_ascii=False, sort_keys=True)]
    if result.final_answer is not None:
        parts.append(json.dumps(result.final_answer, ensure_ascii=False, sort_keys=True))
    if result.failure_report is not None:
        parts.append(json.dumps(result.failure_report, ensure_ascii=False, sort_keys=True))
    return "\n".join(parts)


def _expected_numeric_annotations(value: object) -> list[JsonObject]:
    if not isinstance(value, list):
        return []
    result: list[JsonObject] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        expected = _optional_float(item.get("value"))
        if expected is None:
            continue
        result.append(
            {
                "name": _coerce_text(item.get("name")) or f"numeric-{len(result) + 1}",
                "value": expected,
                "tolerance": _optional_float(item.get("tolerance")),
            }
        )
    return result


def _score_expected_numeric(answer: str, expectation: JsonObject) -> JsonObject:
    expected = _optional_float(expectation.get("value"))
    tolerance = _optional_float(expectation.get("tolerance"))
    numeric = _score_numeric(answer, expected, tolerance)
    return {"name": expectation.get("name"), **numeric}


def _trace_requirement_met(name: str, result: FinanceBenchmarkResult) -> bool:
    normalized = name.strip().lower()
    metrics = result.trace_metrics
    if normalized == "retrieval.run":
        return _int_value(metrics.get("retrieval_run_count")) > 0
    if normalized in {"provided_evidence_context", "benchmark_provided_context", "oracle_context"}:
        return bool(metrics.get("claim_ledger_present")) and _int_value(metrics.get("claim_count")) > 0
    if normalized == "calculator.compute":
        return _int_value(metrics.get("calculator_call_count")) > 0
    if normalized in {"finance_numeric_verification", "finance.verify_numeric", "numeric_verifier"}:
        return isinstance(metrics.get("numeric_verifier_status"), str) and bool(metrics.get("numeric_verifier_status"))
    if normalized in {"finance_fact_ledger", "finance.extract_facts"}:
        return _int_value(metrics.get("finance_fact_count")) > 0
    if normalized == "claim_ledger":
        return bool(metrics.get("claim_ledger_present"))
    if normalized == "slot_frame":
        return bool(metrics.get("slot_frame_present"))
    if normalized == "transform_plan":
        return _int_value(metrics.get("transform_plan_count")) > 0
    if normalized == "verifier_gate":
        return isinstance(metrics.get("verifier_gate_status"), str) and bool(metrics.get("verifier_gate_status"))
    if normalized == "synthesis_gate":
        return isinstance(metrics.get("synthesis_gate_status"), str) and bool(metrics.get("synthesis_gate_status"))
    if normalized in {"citation", "citations", "retrieval_citation"}:
        return bool(result.scorecard.get("citation_present")) or _int_value(metrics.get("citation_count")) > 0
    trace_text = json.dumps(result.to_dict(), ensure_ascii=False, sort_keys=True).casefold()
    return normalized in trace_text


def _source_uris(records: list[JsonObject]) -> list[str]:
    uris: list[str] = []
    for record in records:
        uri = record.get("uri")
        if isinstance(uri, str) and uri:
            uris.append(uri)
    return _ordered_unique(uris)


def _claim_source_uris(claim_ledgers: list[JsonObject]) -> list[str]:
    uris: list[str] = []
    for ledger in claim_ledgers:
        claims = ledger.get("claims") if isinstance(ledger, dict) else None
        if not isinstance(claims, list):
            continue
        for claim in claims:
            if not isinstance(claim, dict):
                continue
            source_ref = claim.get("source_ref")
            if isinstance(source_ref, str) and source_ref:
                uris.append(source_ref)
    return _ordered_unique(uris)


def _target_document_trace_urls(latest_ledger: JsonObject) -> list[str]:
    if not isinstance(latest_ledger, dict):
        return []
    binding = latest_ledger.get("target_document_binding")
    if not isinstance(binding, dict):
        return []
    urls: list[str] = []
    for key in ("doc_link", "source_url"):
        value = binding.get(key)
        if isinstance(value, str) and value:
            urls.append(value)
    source_urls = binding.get("source_urls")
    if isinstance(source_urls, list):
        for value in source_urls:
            if isinstance(value, str) and value:
                urls.append(value)
    return _ordered_unique(urls)


def _claim_source_forms(claim_ledgers: list[JsonObject]) -> list[str]:
    forms: list[str] = []
    for ledger in claim_ledgers:
        claims = ledger.get("claims") if isinstance(ledger, dict) else None
        if not isinstance(claims, list):
            continue
        for claim in claims:
            if not isinstance(claim, dict):
                continue
            metadata = claim.get("metadata") if isinstance(claim.get("metadata"), dict) else {}
            for key in ("doc_type", "form"):
                value = metadata.get(key)
                if isinstance(value, str) and value:
                    forms.append(value)
    return _ordered_unique(forms)


def _claim_citation_count(claim_ledgers: list[JsonObject]) -> int:
    count = 0
    for ledger in claim_ledgers:
        claims = ledger.get("claims") if isinstance(ledger, dict) else None
        if not isinstance(claims, list):
            continue
        for claim in claims:
            if isinstance(claim, dict) and isinstance(claim.get("citation_ref"), str) and claim.get("citation_ref"):
                count += 1
    return count


def _source_hosts(uris: list[str]) -> list[str]:
    hosts: list[str] = []
    for uri in uris:
        host = urllib.parse.urlparse(uri).hostname
        if host:
            hosts.append(host.lower())
    return _ordered_unique(hosts)


def _finance_source_forms(ledgers: list[JsonObject]) -> list[str]:
    forms: list[str] = []
    for ledger in ledgers:
        facts = ledger.get("facts") if isinstance(ledger, dict) else None
        if not isinstance(facts, list):
            continue
        for fact in facts:
            if not isinstance(fact, dict):
                continue
            metadata = fact.get("metadata") if isinstance(fact.get("metadata"), dict) else {}
            form = metadata.get("form")
            if isinstance(form, str) and form:
                forms.append(form)
    return _ordered_unique(forms)


def _transform_methods(transform_plans: list[JsonObject]) -> list[str]:
    methods: list[str] = []
    for plan in transform_plans:
        if not isinstance(plan, dict):
            continue
        for key in ("method", "formula_name", "formula_id", "transform_type", "workflow_type"):
            value = plan.get(key)
            if isinstance(value, str) and value:
                methods.append(value)
        payload = plan.get("payload") if isinstance(plan.get("payload"), dict) else {}
        for key in ("formula_name", "operation", "expression"):
            value = payload.get(key)
            if isinstance(value, str) and value:
                methods.append(value)
    return _ordered_unique(methods)


def _compiled_task_type(program: JsonObject) -> str | None:
    if not isinstance(program, dict):
        return None
    task_spec = program.get("task_spec") if isinstance(program.get("task_spec"), dict) else {}
    value = task_spec.get("task_type")
    if isinstance(value, str) and value:
        return value
    return None


def _compiled_list_count(program: JsonObject, key: str) -> int:
    if not isinstance(program, dict):
        return 0
    value = program.get(key)
    if isinstance(value, list):
        return len(value)
    return 0


def _compiled_missing_slots(program: JsonObject) -> list[str]:
    if not isinstance(program, dict):
        return []
    diagnostics = program.get("diagnostics") if isinstance(program.get("diagnostics"), dict) else {}
    missing = diagnostics.get("missing_slots")
    if isinstance(missing, list):
        return [str(item) for item in missing if str(item)]
    slot_frame = program.get("slot_frame") if isinstance(program.get("slot_frame"), dict) else {}
    missing = slot_frame.get("missing_slots")
    if isinstance(missing, list):
        return [str(item) for item in missing if str(item)]
    return []


def _repeatability_summary(results: list[FinanceBenchmarkResult]) -> tuple[int, float | None]:
    grouped: dict[str, list[FinanceBenchmarkResult]] = {}
    for result in results:
        grouped.setdefault(result.item_id, []).append(result)
    repeated = {item_id: rows for item_id, rows in grouped.items() if len(rows) > 1}
    if not repeated:
        return 0, None
    scores: list[float] = []
    for rows in repeated.values():
        statuses = {row.status for row in rows}
        verifier_statuses = {str(row.trace_metrics.get("numeric_verifier_status")) for row in rows}
        gate_statuses = {str(row.trace_metrics.get("verifier_gate_status")) for row in rows}
        formula_presence = {int(row.trace_metrics.get("formula_trace_count") or 0) > 0 for row in rows}
        citation_presence = {bool(row.scorecard.get("citation_present")) for row in rows}
        components = [
            len(statuses) == 1,
            len(verifier_statuses) == 1,
            len(gate_statuses) == 1,
            len(formula_presence) == 1,
            len(citation_presence) == 1,
        ]
        scores.append(_rate(sum(1 for item in components if item), len(components)))
    return len(repeated), _average(scores)


def _benchmark_split_payload(split: FinanceBenchmarkSplitSpec | JsonObject | None) -> JsonObject:
    if split is None:
        return {}
    if isinstance(split, FinanceBenchmarkSplitSpec):
        return split.to_dict()
    if isinstance(split, dict):
        return dict(split)
    return {}


def _load_records(path: Path) -> list[JsonObject]:
    text = path.read_text(encoding="utf-8")
    stripped = text.strip()
    if not stripped:
        return []
    if path.suffix.lower() in {".jsonl", ".ndjson"}:
        return _load_jsonl_records(text)
    if stripped.startswith("["):
        payload = json.loads(stripped)
        if not isinstance(payload, list):
            raise ValueError(f"expected JSON array in {path}")
        return [dict(item) for item in payload if isinstance(item, dict)]
    if stripped.startswith("{"):
        payload = json.loads(stripped)
        if isinstance(payload, dict):
            for key in ("data", "items", "questions", "records", "test"):
                value = payload.get(key)
                if isinstance(value, list):
                    return [dict(item) for item in value if isinstance(item, dict)]
            if "question" in payload or "prompt" in payload or "query" in payload:
                return [payload]
        raise ValueError(f"expected a JSONL file or a JSON object with data/items/questions in {path}")
    return _load_jsonl_records(text)


def _run_one_finance_benchmark_item(
    index: int,
    item: FinanceBenchmarkItem,
    runtime_factory: Callable[[int, FinanceBenchmarkItem], ChatRuntimeLike],
    thread_prefix: str,
    question_prefix: str,
) -> FinanceBenchmarkResult:
    runtime = runtime_factory(index, item)
    journal = getattr(runtime, "journal", None)
    thread_id = f"{safe_storage_id(thread_prefix)}-{index:04d}-{safe_storage_id(item.item_id)}"
    prompt = _benchmark_prompt(item, question_prefix=question_prefix)
    payload = runtime.receive(prompt, thread_id=thread_id)
    answer = _answer_from_chat_result(payload)
    _append_benchmark_provided_context_trace(journal, item=item, task_id=payload.task_id, run_id=payload.run_id)
    metrics = trace_metrics(journal, task_id=payload.task_id)
    scorecard = score_finance_answer(
        item,
        answer=answer,
        final_answer=payload.final_answer,
        failure_report=payload.failure_report,
        trace_metrics=metrics,
    )
    result = FinanceBenchmarkResult(
        item_id=item.item_id,
        status=str(scorecard["status"]),
        question=item.question,
        answer=answer,
        task_id=payload.task_id,
        run_id=payload.run_id,
        thread_id=payload.thread_id,
        scorecard=scorecard,
        trace_metrics=metrics,
        trace_refs=list(payload.trace_refs),
        final_answer=payload.final_answer,
        failure_report=payload.failure_report,
        metadata={
            "category": item.category,
            "source": item.source,
            "required_tools": list(item.required_tools),
            "workflow_type": item.workflow_type,
            "required_slots": list(item.required_slots),
            "evidence_policy": dict(item.evidence_policy),
            "required_transforms": list(item.required_transforms),
            "dealbreakers": list(item.dealbreakers),
            "expected_trace": list(item.expected_trace),
            "failure_taxonomy": list(item.failure_taxonomy),
            "parallel_index": index,
        },
    )
    if journal is not None:
        journal.append(
            task_id=payload.task_id,
            run_id=payload.run_id or "finance-benchmark",
            step_id=None,
            kind="finance_benchmark_item_result",
            data=result.to_dict(),
            state_delta={"finance_benchmark_status": result.status, "finance_benchmark_item_id": item.item_id},
        )
    return result


def _load_jsonl_records(text: str) -> list[JsonObject]:
    records: list[JsonObject] = []
    for line in text.splitlines():
        if not line.strip():
            continue
        payload = json.loads(line)
        if isinstance(payload, dict):
            records.append(payload)
    return records


def _item_from_record(record: JsonObject, *, index: int) -> FinanceBenchmarkItem:
    item_id = _coerce_text(_first_present(record, "id", "question_id", "benchmark_id", "qid", "item_id")) or f"item-{index}"
    question = _coerce_text(_first_present(record, "question", "prompt", "query", "task", "input"))
    if not question:
        raise ValueError(f"benchmark item {item_id} is missing a question")
    gold_answer = _optional_text(_first_present(record, "gold_answer", "answer", "expected_answer", "reference_answer", "gold"))
    metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
    metadata = dict(metadata)
    metadata["raw_keys"] = sorted(str(key) for key in record.keys())
    for key in ("prompt_context", "rubric", "source_refs", "benchmark_homepage", "benchmark_dataset_url", "default_scoring"):
        if key in record and key not in metadata:
            metadata[key] = record[key]
    evidence_policy = _json_object_value(_first_present(record, "evidence_policy", "source_policy") or metadata.get("evidence_policy"))
    return FinanceBenchmarkItem(
        item_id=item_id,
        question=question,
        gold_answer=gold_answer,
        numeric_value=_optional_float(_first_present(record, "numeric_value", "gold_value", "answer_numeric", "value")),
        tolerance=_optional_float(_first_present(record, "tolerance", "numeric_tolerance", "answer_tolerance")),
        evidence_excerpt=_optional_text(
            _first_present(record, "evidence_excerpt", "supporting_evidence", "evidence", "supporting_evidence_excerpt")
        ),
        required_tools=_string_list(_first_present(record, "required_tools", "tools", "tool_annotations")),
        category=_optional_text(_first_present(record, "type", "category", "task_type", "label")),
        source=_optional_text(_first_present(record, "source", "benchmark", "dataset")),
        workflow_type=_optional_text(_first_present(record, "workflow_type", "workflow", "work_type") or metadata.get("workflow_type")),
        required_slots=_string_list(_first_present(record, "required_slots", "slots") or metadata.get("required_slots")),
        evidence_policy=evidence_policy,
        required_transforms=_string_list(_first_present(record, "required_transforms", "transforms") or metadata.get("required_transforms")),
        dealbreakers=_string_list(_first_present(record, "dealbreakers", "deal_breakers") or metadata.get("dealbreakers")),
        expected_trace=_string_list(_first_present(record, "expected_trace", "required_trace") or metadata.get("expected_trace")),
        failure_taxonomy=_string_list(_first_present(record, "failure_taxonomy", "failure_labels") or metadata.get("failure_taxonomy")),
        metadata=metadata,
    )


def _prediction_map(records: list[JsonObject]) -> dict[str, JsonObject]:
    predictions: dict[str, JsonObject] = {}
    for index, record in enumerate(records, start=1):
        item_id = _coerce_text(_first_present(record, "id", "item_id", "question_id", "benchmark_id", "qid")) or f"item-{index}"
        predictions[item_id] = record
    return predictions


def _benchmark_prompt(item: FinanceBenchmarkItem, *, question_prefix: str) -> str:
    parts: list[str] = []
    prefix = question_prefix.strip()
    if prefix:
        parts.append(prefix)
    context = item.metadata.get("prompt_context")
    if isinstance(context, str) and context.strip():
        import_mode = str(item.metadata.get("import_mode") or "").strip().lower()
        if import_mode in {"oracle_evidence", "oracle_context"}:
            instruction = (
                "Benchmark-provided oracle source context follows. Treat it as authorized source evidence. "
                "This item is in oracle-context mode: external retrieval is not required. First solve directly from this context "
                "when it contains the needed information; do not call live retrieval only to reacquire the same benchmark source. "
                "Do not fail merely because retrieval_evidence or citation_refs are absent when the provided context answers the question. "
                "When answering, cite the provided document link or provided context explicitly."
            )
        elif import_mode == "doc_retrieval":
            instruction = (
                "Benchmark target source follows. Acquire evidence from Source URL first; it is not answer evidence by itself. "
                "Prefer direct URL fetch before broad search. This is an answerable public benchmark item: the target "
                "document or its primary filing data should contain enough information to solve it. Do not treat an "
                "initial missing slot, unsupported-number verifier result, or synthesis-gate failure as a final answer. "
                "If the first path fails, continue by changing method: read the target filing, parse tables, use "
                "script.exec/shell.exec when available, extract structured facts, run calculator.compute when needed, "
                "and then answer from ClaimLedger or FormulaTrace-backed numbers."
            )
            context = _doc_retrieval_context_for_prompt(item) or context
        else:
            instruction = "Benchmark-provided source context follows. Use it as evidence when relevant."
        parts.append(
            f"{instruction}\n\n{context.strip()}"
        )
    parts.append(item.question)
    return "\n\n".join(parts)


def _doc_retrieval_context_for_prompt(item: FinanceBenchmarkItem) -> str:
    lines: list[str] = []
    source_url = _benchmark_context_source_ref(item)
    if source_url and not source_url.startswith("benchmark:"):
        lines.append(f"Source URL: {source_url}")
    for label, key in (
        ("Company", "company"),
        ("Document", "doc_name"),
        ("Document type", "doc_type"),
        ("Document period", "doc_period"),
    ):
        value = _benchmark_metadata_text(item, key)
        if value:
            lines.append(f"{label}: {value}")
    return "\n".join(lines).strip()


def _append_benchmark_provided_context_trace(
    journal: JournalStore | None,
    *,
    item: FinanceBenchmarkItem,
    task_id: str | None,
    run_id: str | None,
) -> None:
    if journal is None or not task_id:
        return
    import_mode = str(item.metadata.get("import_mode") or "").strip().lower()
    if import_mode in {"doc_retrieval", "question_only"}:
        return
    context = item.evidence_excerpt or item.metadata.get("prompt_context")
    if not isinstance(context, str) or not context.strip():
        return
    effective_run_id = run_id or "finance-benchmark"
    source_ref = _benchmark_context_source_ref(item)
    claim = Claim(
        claim_id=f"claim-benchmark-{safe_storage_id(item.item_id)}",
        domain=str(item.workflow_type or "source_grounded_research"),
        entity=_benchmark_metadata_text(item, "company"),
        attribute="benchmark_provided_context",
        value=_preview(context, 1200),
        time_period=_benchmark_metadata_text(item, "doc_period"),
        source_ref=source_ref,
        evidence_ref=f"benchmark-evidence-{safe_storage_id(item.item_id)}",
        citation_ref=f"cite-benchmark-{safe_storage_id(item.item_id)}",
        extraction_method="benchmark_provided_context",
        confidence=1.0,
        metadata={
            "benchmark": item.source,
            "category": item.category,
            "import_mode": item.metadata.get("import_mode"),
            "doc_name": item.metadata.get("doc_name"),
            "doc_type": item.metadata.get("doc_type"),
            "context_chars": len(context),
        },
    )
    claim_record = journal.append(
        task_id=task_id,
        run_id=effective_run_id,
        step_id=None,
        kind="claim_ledger",
        data={
            "schema": "holo.kernel_v3.claim_ledger.v1",
            "domain": claim.domain,
            "purpose": "benchmark_provided_context",
            "claim_count": 1,
            "claims": [claim.to_dict()],
            "source": "benchmark_harness",
        },
        state_delta={"claim_count": 1},
    )
    frame = _benchmark_context_slot_frame(item, claim=claim, claim_record_id=claim_record.record_id)
    journal.append(
        task_id=task_id,
        run_id=effective_run_id,
        step_id=None,
        kind="slot_frame",
        data={**frame.to_dict(), "schema": "holo.kernel_v3.slot_frame.v1", "source": "benchmark_harness"},
        state_delta={"slot_frame_task_type": frame.task_type, "missing_slot_count": len(frame.missing_slots)},
    )
    transform = TransformPlan(
        plan_id=f"transform-benchmark-{safe_storage_id(item.item_id)}",
        domain=claim.domain,
        operation="synthesize" if not item.required_transforms else "compute_or_synthesize",
        status="ready" if not frame.missing_slots else "missing_slots",
        method="benchmark_context_workflow",
        input_claim_ids=[claim.claim_id],
        output_attribute="answer",
        payload=None,
        missing_slots=list(frame.missing_slots),
        diagnostics={"source": "benchmark_harness", "required_transforms": list(item.required_transforms)},
    )
    journal.append(
        task_id=task_id,
        run_id=effective_run_id,
        step_id=None,
        kind="transform_plan",
        data={**transform.to_dict(), "schema": "holo.kernel_v3.transform_plan.v1"},
        state_delta={"transform_plan_status": transform.status},
    )
    gate = VerificationGateResult(
        gate_id=f"verifier-benchmark-{safe_storage_id(item.item_id)}",
        domain=claim.domain,
        status="passed" if claim.value and source_ref else "failed",
        policy_id=frame.evidence_policy.policy_id if frame.evidence_policy else None,
        issues=[] if claim.value and source_ref else [{"code": "missing_benchmark_context_source"}],
        matched_claims=[{"claim_id": claim.claim_id, "source_ref": source_ref}],
        missing_slots=list(frame.missing_slots),
        diagnostics={"source": "benchmark_harness_context_trace"},
    )
    journal.append(
        task_id=task_id,
        run_id=effective_run_id,
        step_id=None,
        kind="verifier_gate_result",
        data={**gate.to_dict(), "schema": "holo.kernel_v3.verifier_gate_result.v1"},
        state_delta={"verifier_gate_status": gate.status},
    )


def _benchmark_context_slot_frame(item: FinanceBenchmarkItem, *, claim: Claim, claim_record_id: str) -> SlotFrame:
    required_names = list(item.required_slots) or ["source", "claim"]
    specs = [
        SlotSpec(
            name=name,
            requirement="required",
            accepted_attributes=[name, "benchmark_provided_context"],
            source_requirements=["benchmark_provided_context"],
        )
        for name in required_names
    ]
    fills: list[SlotFill] = []
    missing: list[str] = []
    for name in required_names:
        value = _benchmark_slot_value(item, name, claim)
        if value:
            fills.append(
                SlotFill(
                    slot_name=name,
                    claim_id=claim.claim_id,
                    value=value,
                    source_ref=claim.source_ref,
                    confidence=1.0,
                    metadata={"claim_ledger_ref": claim_record_id},
                )
            )
        else:
            missing.append(name)
    policy_payload = item.evidence_policy if isinstance(item.evidence_policy, dict) else {}
    policy = EvidencePolicy(
        policy_id=f"evidence-policy-benchmark-{safe_storage_id(item.item_id)}",
        domain=claim.domain,
        required_source_families=_string_list(policy_payload.get("required_source_families")) or ["benchmark_provided_context"],
        forbidden_source_families=_string_list(policy_payload.get("forbidden_source_families")),
        required_terms=_string_list(policy_payload.get("required_terms")),
        authority=str(policy_payload.get("authority") or "benchmark_provided_context"),
        diagnostics={"source": "benchmark_harness", "import_mode": item.metadata.get("import_mode")},
    )
    return SlotFrame(
        frame_id=f"slot-frame-benchmark-{safe_storage_id(item.item_id)}",
        task_type=str(item.workflow_type or "source_grounded_research"),
        domain=claim.domain,
        required_slots=specs,
        optional_slots=[],
        filled_slots=fills,
        missing_slots=_ordered_unique(missing),
        evidence_policy=policy,
        diagnostics={"source": "benchmark_harness", "claim_ledger_ref": claim_record_id},
    )


def _benchmark_slot_value(item: FinanceBenchmarkItem, name: str, claim: Claim) -> str | None:
    normalized = _norm_key(name)
    if normalized in {"source", "citation"}:
        return claim.source_ref or claim.citation_ref
    if normalized in {"claim", "question_context"}:
        return claim.value
    if normalized in {"entity", "issuer", "company", "entity_a", "entity_b"}:
        return _benchmark_metadata_text(item, "company") or claim.entity
    if normalized in {"period", "event_period", "doc_period"}:
        return _benchmark_metadata_text(item, "doc_period") or claim.time_period
    if normalized in {"input_values", "formula_or_operation", "answer_unit"}:
        return claim.value if item.source == "finqa" else None
    return None


def _benchmark_context_source_ref(item: FinanceBenchmarkItem) -> str:
    refs = item.metadata.get("source_refs") if isinstance(item.metadata.get("source_refs"), list) else []
    for ref in refs:
        if not isinstance(ref, dict):
            continue
        url = _coerce_text(ref.get("url"))
        if url:
            return url
    for key in ("doc_link", "source_url", "benchmark_dataset_url"):
        value = _benchmark_metadata_text(item, key)
        if value:
            return value
    return f"benchmark:{item.source or 'finance'}:{item.item_id}"


def _benchmark_metadata_text(item: FinanceBenchmarkItem, key: str) -> str | None:
    value = item.metadata.get(key) if isinstance(item.metadata, dict) else None
    text = _coerce_text(value)
    return text or None


def _answer_from_chat_result(payload: ChatRuntimeResult) -> str:
    if payload.final_answer is not None:
        answer = payload.final_answer.get("answer")
        if isinstance(answer, str):
            return answer
    if payload.answer:
        return payload.answer
    if payload.failure_report is not None:
        next_action = payload.failure_report.get("next_possible_action")
        reason = payload.failure_report.get("reason")
        return " ".join(str(value) for value in (reason, next_action) if isinstance(value, str))
    return ""


def _citation_refs(final_answer: JsonObject | None, *, answer_text: str) -> list[str]:
    refs: list[str] = []
    if isinstance(final_answer, dict):
        value = final_answer.get("citation_refs")
        if isinstance(value, list):
            refs.extend(str(item) for item in value if item)
    refs.extend(re.findall(r"\bcite-[A-Za-z0-9_.:-]+\b", answer_text))
    return sorted(set(refs))


def _score_numeric(answer: str, expected: float | None, tolerance: float | None) -> JsonObject:
    if expected is None:
        return {"scored": False, "passed": None, "expected": None, "tolerance": None, "matched_value": None, "values": []}
    values = _extract_numeric_values(answer)
    tol = abs(float(tolerance)) if tolerance is not None else max(abs(expected) * 0.01, 1e-9)
    matched = None
    for value in values:
        if abs(value - expected) <= tol:
            matched = value
            break
    return {
        "scored": True,
        "passed": matched is not None,
        "expected": expected,
        "tolerance": tol,
        "matched_value": matched,
        "values": values[:32],
    }


def _numeric_target_from_gold(gold: str) -> float | None:
    candidates = _extract_numeric_candidates(gold)
    if not candidates:
        return None
    preferred = [
        candidate
        for candidate in candidates
        if (candidate["prefix"] or candidate["unit"]) and not _looks_like_year(float(candidate["value"]))
    ]
    if preferred:
        return float(preferred[0]["value"])
    for candidate in candidates:
        value = float(candidate["value"])
        if not _looks_like_year(value):
            return value
    return float(candidates[0]["value"])


def _extract_numeric_values(text: str) -> list[float]:
    return [float(candidate["value"]) for candidate in _extract_numeric_candidates(text)]


def _extract_numeric_candidates(text: str) -> list[JsonObject]:
    candidates: list[JsonObject] = []
    pattern = re.compile(
        r"(?P<prefix>[$€£¥])?\s*(?P<number>-?\d+(?:,\d{3})*(?:\.\d+)?|-?\d+(?:\.\d+)?)\s*"
        r"(?P<unit>%|million|billion|trillion|thousand|mn|bn|m|b|亿|万)?",
        re.IGNORECASE,
    )
    for match in pattern.finditer(text):
        raw = match.group("number").replace(",", "")
        try:
            value = float(raw)
        except ValueError:
            continue
        unit = (match.group("unit") or "").lower()
        prefix = match.group("prefix") or ""
        if _ambiguous_compact_scale_unit(text, match, raw=raw, prefix=prefix, unit=unit):
            continue
        if unit in {"million", "mn", "m"}:
            value *= 1_000_000
        elif unit in {"billion", "bn", "b"}:
            value *= 1_000_000_000
        elif unit == "trillion":
            value *= 1_000_000_000_000
        elif unit == "thousand":
            value *= 1_000
        elif unit == "亿":
            value *= 100_000_000
        elif unit == "万":
            value *= 10_000
        if math.isfinite(value):
            candidates.append(
                {
                    "value": value,
                    "raw_number": raw,
                    "raw_token": match.group(0).strip(),
                    "prefix": prefix,
                    "unit": unit,
                }
            )
    return candidates


def _ambiguous_compact_scale_unit(text: str, match: re.Match[str], *, raw: str, prefix: str, unit: str) -> bool:
    if unit not in {"m", "b"} or prefix:
        return False
    unit_start = match.start("unit")
    if unit_start < 0:
        return False
    separator = text[match.end("number") : unit_start]
    if separator:
        return False
    if "." in raw:
        return False
    # Bare compact tokens such as "3M" are frequently company names, tickers,
    # product labels, or identifiers. Keep explicit currency or word-scale
    # forms ("$3M", "3 million") but avoid turning names into gold numerics.
    return True


def _looks_like_year(value: float) -> bool:
    return value.is_integer() and 1900 <= value <= 2100


def _gold_sentinel(gold: str) -> bool:
    normalized = _normalize_text(gold).replace(" ", "_").upper()
    return any(sentinel in normalized for sentinel in SENTINEL_GOLD_ANSWERS)


def _token_overlap(expected: str, actual: str) -> float:
    expected_tokens = _tokens(expected)
    actual_tokens = _tokens(actual)
    if not expected_tokens:
        return 0.0
    return round(len(expected_tokens & actual_tokens) / len(expected_tokens), 4)


def _tokens(text: str) -> set[str]:
    return {token for token in re.findall(r"[A-Za-z0-9]+", _normalize_text(text)) if len(token) > 1}


def _normalize_text(text: str) -> str:
    return " ".join(str(text or "").casefold().split())


def _contains_any(text: str, markers: tuple[str, ...]) -> bool:
    return any(marker in text for marker in markers)


def _first_present(data: JsonObject, *keys: str) -> JsonValue:
    for key in keys:
        if key in data and data[key] not in (None, ""):
            return data[key]
    return None


def _coerce_text(value: JsonValue) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _preview(text: str, limit: int) -> str:
    normalized = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(normalized) <= limit:
        return normalized
    return normalized[: max(0, limit - 1)].rstrip() + "…"


def _optional_text(value: JsonValue) -> str | None:
    text = _coerce_text(value)
    return text or None


def _optional_str(value: object) -> str | None:
    return str(value) if isinstance(value, str) and value else None


def _optional_float(value: JsonValue) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        text = value.replace(",", "").strip()
        if not text:
            return None
        try:
            return float(text)
        except ValueError:
            return None
    return None


def _json_object_value(value: object) -> JsonObject:
    return dict(value) if isinstance(value, dict) else {}


def _string_list(value: JsonValue) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if item is not None]
    if isinstance(value, dict):
        return [str(key) for key, enabled in value.items() if enabled]
    if isinstance(value, str) and value.strip():
        return [part.strip() for part in value.split(",") if part.strip()]
    return []


def _norm_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value or "").casefold()).strip("_")


def _count_scorecard(results: list[FinanceBenchmarkResult], key: str) -> int:
    return sum(1 for result in results if bool(result.scorecard.get(key)))


def _average_metric(results: list[FinanceBenchmarkResult], key: str) -> float:
    values = []
    for result in results:
        value = result.trace_metrics.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            values.append(float(value))
    return _average(values)


def _average(values: list[float]) -> float:
    if not values:
        return 0.0
    return round(sum(values) / len(values), 4)


def _rate(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator, 4)


def _int_value(value: object) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return int(value)
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
