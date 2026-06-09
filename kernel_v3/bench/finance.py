from __future__ import annotations

import json
import math
import re
import time
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
    status_counts: JsonObject
    output_path: str | None = None


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


def summarize_finance_benchmark(results: list[FinanceBenchmarkResult], *, output_path: Path | None = None) -> FinanceBenchmarkSummary:
    status_counts = Counter(result.status for result in results)
    scored = [result for result in results if bool(result.scorecard.get("scored"))]
    numeric_scored = [
        result for result in results if isinstance(result.scorecard.get("numeric"), dict) and result.scorecard["numeric"].get("scored")
    ]
    adversarial_scored = [result for result in results if bool(result.scorecard.get("gold_sentinel"))]
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
        status_counts=dict(status_counts),
        output_path=str(output_path) if output_path is not None else None,
    )


def write_finance_benchmark_outputs(
    results: list[FinanceBenchmarkResult],
    *,
    output_path: Path | str | None,
    summary_path: Path | str | None = None,
    journal: JournalStore | None = None,
) -> FinanceBenchmarkSummary:
    output = Path(output_path) if output_path is not None else None
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            "\n".join(json.dumps(result.to_dict(), ensure_ascii=False, sort_keys=True) for result in results) + "\n",
            encoding="utf-8",
        )
    summary = summarize_finance_benchmark(results, output_path=output)
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


def finance_benchmark_run_id() -> str:
    return "finbench-" + str(int(time.time() * 1000))


def trace_metrics(journal: JournalStore | None, *, task_id: str | None) -> JsonObject:
    if journal is None or task_id is None:
        return {}
    records = journal.records(task_id=task_id)
    processor_results = [record.data for record in records if record.kind == "processor_result"]
    actions = [record.data for record in records if record.kind == "action"]
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
        "final_answer_chars": retrieval.get("final_answer_chars", 0),
        "latest_failure_mode": retrieval.get("latest_failure_mode"),
        "latest_next_strategy_hint": retrieval.get("latest_next_strategy_hint"),
    }


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
        metadata={"raw_keys": sorted(str(key) for key in record.keys())},
    )


def _prediction_map(records: list[JsonObject]) -> dict[str, JsonObject]:
    predictions: dict[str, JsonObject] = {}
    for index, record in enumerate(records, start=1):
        item_id = _coerce_text(_first_present(record, "id", "item_id", "question_id", "benchmark_id", "qid")) or f"item-{index}"
        predictions[item_id] = record
    return predictions


def _benchmark_prompt(item: FinanceBenchmarkItem, *, question_prefix: str) -> str:
    prefix = question_prefix.strip()
    if not prefix:
        return item.question
    return f"{prefix}\n\n{item.question}"


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
        if isinstance(value, (int, float)):
            values.append(float(value))
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
