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


SENTINEL_GOLD_ANSWERS = {"INCORRECT_PREMISE", "NOT_AVAILABLE", "NOT ENOUGH INFORMATION"}
UNAVAILABLE_MARKERS = (
    "not available",
    "incorrect premise",
    "insufficient evidence",
    "not enough information",
    "cannot determine",
    "can't determine",
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
    metadata: JsonObject = field(default_factory=dict)


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
    transform_plan_present_rate: float
    average_transform_plans: float
    slot_frame_present_rate: float
    average_missing_slots: float
    average_claims: float
    average_finance_facts: float
    numeric_verifier_pass_rate: float | None
    verifier_gate_pass_rate: float | None
    synthesis_gate_pass_rate: float | None
    average_answer_numeric_support_rate: float | None
    finance_numeric_failure_reason_counts: JsonObject
    status_counts: JsonObject
    output_path: str | None = None
    dev_annotation_score: JsonObject | None = None


FinanceBenchmarkResultCallback = Callable[[int, FinanceBenchmarkItem, FinanceBenchmarkResult], None]


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
    answer_present = bool(normalized_answer.strip())

    scored = False
    passed = False
    reason = "ungraded_no_gold_signal"
    if gold_sentinel:
        scored = True
        passed = (unavailable_ack or corrected_actual) and answer_present
        if corrected_actual:
            reason = "sentinel_actual_value_corrected"
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

    return {
        "schema": "holo.kernel_v3.finance_benchmark_score.v1",
        "status": status,
        "scored": scored,
        "reason": reason,
        "answer_present": answer_present,
        "gold_sentinel": gold_sentinel,
        "unavailable_acknowledged": unavailable_ack,
        "corrected_actual_value": corrected_actual,
        "gold_string_match": gold_string_match,
        "gold_token_overlap": gold_overlap,
        "numeric": numeric,
        "citation_present": citation_present,
        "citation_refs": citation_refs[:64],
        "failure_report_present": failure_report is not None,
        "trace_metrics": dict(trace_metrics or {}),
    }


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
                metadata={"source": "prediction_file", "category": item.category},
            )
        )
    return results


def summarize_finance_benchmark(
    results: list[FinanceBenchmarkResult],
    *,
    output_path: Path | None = None,
    annotation_path: Path | str | None = None,
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
        transform_plan_present_rate=_rate(sum(1 for result in results if int(result.trace_metrics.get("transform_plan_count") or 0) > 0), len(results)),
        average_transform_plans=_average_metric(results, "transform_plan_count"),
        slot_frame_present_rate=_rate(sum(1 for result in results if bool(result.trace_metrics.get("slot_frame_present"))), len(results)),
        average_missing_slots=_average_metric(results, "missing_slot_count"),
        average_claims=_average_metric(results, "claim_count"),
        average_finance_facts=_average_metric(results, "finance_fact_count"),
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
        average_answer_numeric_support_rate=_average(support_rates) if support_rates else None,
        finance_numeric_failure_reason_counts=dict(numeric_failure_reasons),
        status_counts=dict(status_counts),
        output_path=str(output_path) if output_path is not None else None,
        dev_annotation_score=score_finance_dev_annotations(results, annotation_path=annotation_path)
        if annotation_path is not None
        else None,
    )


def write_finance_benchmark_outputs(
    results: list[FinanceBenchmarkResult],
    *,
    output_path: Path | str | None,
    summary_path: Path | str | None = None,
    annotation_path: Path | str | None = None,
    journal: JournalStore | None = None,
) -> FinanceBenchmarkSummary:
    output = Path(output_path) if output_path is not None else None
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            "\n".join(json.dumps(result.to_dict(), ensure_ascii=False, sort_keys=True) for result in results) + "\n",
            encoding="utf-8",
        )
    summary = summarize_finance_benchmark(results, output_path=output, annotation_path=annotation_path)
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
    behavior_score = _average(behavior_scores) if behavior_scores else None
    numeric_score = _average(numeric_scores) if numeric_scores else None
    substrate_score = _average(substrate_scores) if substrate_scores else None
    component_scores = [score for score in (behavior_score, numeric_score, substrate_score) if isinstance(score, float)]
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
        "overall_score": _average(component_scores) if component_scores else None,
        "failure_reason_counts": dict(failure_reasons),
        "items": item_scores,
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
    verifier_gates = [record.data for record in records if record.kind == "verifier_gate_result"]
    synthesis_gates = [record.data for record in records if record.kind == "synthesis_gate_result"]
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
    latest_verifier_gate = verifier_gates[-1] if verifier_gates else {}
    latest_synthesis_gate = synthesis_gates[-1] if synthesis_gates else {}
    latest_verification = numeric_verifications[-1] if numeric_verifications else {}
    latest_verification = latest_verification if isinstance(latest_verification, dict) else {}
    verification_diagnostics = latest_verification.get("diagnostics") if isinstance(latest_verification.get("diagnostics"), dict) else {}
    answer_numeric_count = _int_value(verification_diagnostics.get("answer_numeric_count"))
    matched_values = latest_verification.get("matched_values") if isinstance(latest_verification.get("matched_values"), list) else []
    issue_codes = _finance_numeric_issue_codes(latest_verification)
    numeric_verifier_status = latest_verification.get("status") if isinstance(latest_verification.get("status"), str) else None
    verifier_gate_status = latest_verifier_gate.get("status") if isinstance(latest_verifier_gate.get("status"), str) else None
    verifier_gate_issues = latest_verifier_gate.get("issues") if isinstance(latest_verifier_gate.get("issues"), list) else []
    synthesis_gate_status = latest_synthesis_gate.get("status") if isinstance(latest_synthesis_gate.get("status"), str) else None
    synthesis_gate_issues = latest_synthesis_gate.get("issues") if isinstance(latest_synthesis_gate.get("issues"), list) else []
    answer_numeric_support_rate = _rate(len(matched_values), answer_numeric_count) if answer_numeric_count else None
    source_uris = _source_uris([*retrieval_evidence_records, *retrieval_citation_records])
    source_hosts = _source_hosts(source_uris)
    finance_source_forms = _finance_source_forms(finance_ledgers)
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
        "citation_count": retrieval.get("citation_count", 0),
        "calculator_used": bool(calculator_observations),
        "calculator_call_count": len(calculator_observations),
        "formula_trace_present": bool(formula_trace_ids),
        "formula_trace_count": len(formula_trace_ids),
        "claim_ledger_present": bool(claim_ledgers),
        "claim_count": _int_value(latest_claim_ledger.get("claim_count")) if isinstance(latest_claim_ledger, dict) else 0,
        "transform_plan_present": bool(transform_plans),
        "transform_plan_count": len(transform_plans),
        "ready_transform_plan_count": sum(1 for item in transform_plans if item.get("status") == "ready"),
        "missing_slot_transform_plan_count": sum(1 for item in transform_plans if item.get("status") == "missing_slots"),
        "slot_frame_present": bool(slot_frames),
        "slot_frame_task_type": latest_slot_frame.get("task_type") if isinstance(latest_slot_frame, dict) else None,
        "missing_slot_count": len(latest_slot_frame.get("missing_slots") or []) if isinstance(latest_slot_frame, dict) else 0,
        "missing_slots": latest_slot_frame.get("missing_slots") if isinstance(latest_slot_frame, dict) else [],
        "finance_fact_count": _int_value(latest_ledger.get("fact_count")) if isinstance(latest_ledger, dict) else 0,
        "numeric_verifier_status": numeric_verifier_status,
        "numeric_verifier_passed": numeric_verifier_status == "passed" if numeric_verifier_status else None,
        "numeric_verifier_pass_rate": 1.0 if numeric_verifier_status == "passed" else 0.0 if numeric_verifier_status == "failed" else None,
        "verifier_gate_status": verifier_gate_status,
        "verifier_gate_passed": verifier_gate_status == "passed" if verifier_gate_status else None,
        "verifier_gate_issue_count": len(verifier_gate_issues),
        "synthesis_gate_status": synthesis_gate_status,
        "synthesis_gate_passed": synthesis_gate_status == "passed" if synthesis_gate_status else None,
        "synthesis_gate_issue_count": len(synthesis_gate_issues),
        "answer_numeric_support_rate": answer_numeric_support_rate,
        "finance_numeric_failure_reason": issue_codes[0] if issue_codes else None,
        "finance_numeric_failure_reasons": issue_codes,
        "source_hosts": source_hosts[:64],
        "source_uris": source_uris[:64],
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
    required_trace = _string_list(annotation.get("required_trace"))
    trace_hits = [name for name in required_trace if _trace_requirement_met(name, result)]
    required_sources = _string_list(annotation.get("required_sources"))
    source_hits = [name for name in required_sources if name.casefold() in haystack.casefold()]
    behavior_denominator = len(expected_contains) + len(required_sources)
    behavior_numerator = len(contains_hits) + len(source_hits)
    numeric_denominator = len(numeric_matches)
    numeric_numerator = sum(1 for item in numeric_matches if item.get("passed") is True)
    substrate_denominator = len(required_trace)
    substrate_numerator = len(trace_hits)
    failure_reasons: list[str] = []
    if len(contains_hits) < len(expected_contains):
        failure_reasons.append("expected_answer_content_missing")
    if len(source_hits) < len(required_sources):
        failure_reasons.append("required_source_missing")
    if numeric_denominator and numeric_numerator < numeric_denominator:
        failure_reasons.append("expected_numeric_mismatch")
    if substrate_denominator and substrate_numerator < substrate_denominator:
        failure_reasons.append("required_trace_missing")
    return {
        "item_id": result.item_id,
        "behavior_score": _rate(behavior_numerator, behavior_denominator) if behavior_denominator else None,
        "numeric_score": _rate(numeric_numerator, numeric_denominator) if numeric_denominator else None,
        "substrate_score": _rate(substrate_numerator, substrate_denominator) if substrate_denominator else None,
        "expected_contains_count": len(expected_contains),
        "expected_contains_hit_count": len(contains_hits),
        "expected_numeric_count": len(numeric_expectations),
        "expected_numeric_hit_count": numeric_numerator,
        "required_trace_count": len(required_trace),
        "required_trace_hit_count": len(trace_hits),
        "required_source_count": len(required_sources),
        "required_source_hit_count": len(source_hits),
        "numeric_matches": numeric_matches,
        "missing_trace": [name for name in required_trace if name not in trace_hits],
        "missing_sources": [name for name in required_sources if name not in source_hits],
        "failure_reasons": failure_reasons,
    }


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
    if normalized == "calculator.compute":
        return _int_value(metrics.get("calculator_call_count")) > 0
    if normalized in {"finance_numeric_verification", "finance.verify_numeric", "numeric_verifier"}:
        return isinstance(metrics.get("numeric_verifier_status"), str) and bool(metrics.get("numeric_verifier_status"))
    if normalized in {"finance_fact_ledger", "finance.extract_facts"}:
        return _int_value(metrics.get("finance_fact_count")) > 0
    trace_text = json.dumps(result.to_dict(), ensure_ascii=False, sort_keys=True).casefold()
    return normalized in trace_text


def _source_uris(records: list[JsonObject]) -> list[str]:
    uris: list[str] = []
    for record in records:
        uri = record.get("uri")
        if isinstance(uri, str) and uri:
            uris.append(uri)
    return _ordered_unique(uris)


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
        parts.append(
            "Benchmark-provided source context follows. Use it as evidence, but do not assume it is complete.\n\n"
            f"{context.strip()}"
        )
    parts.append(item.question)
    return "\n\n".join(parts)


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
                    "prefix": match.group("prefix") or "",
                    "unit": unit,
                }
            )
    return candidates


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


def _string_list(value: JsonValue) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if item is not None]
    if isinstance(value, dict):
        return [str(key) for key, enabled in value.items() if enabled]
    if isinstance(value, str) and value.strip():
        return [part.strip() for part in value.split(",") if part.strip()]
    return []


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
