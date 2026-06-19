from __future__ import annotations

import argparse
import asyncio
import csv
import json
import re
import sys
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from kernel_v4.contracts import JsonObject, LoopEvent, LoopResult, ModelClient
from kernel_v4.finance_costs import estimate_deepseek_cost_usd
from kernel_v4.finance_run import _transcript_preview, _usage_summary
from kernel_v4.finance_runner import FinanceQuestionSpec, run_finance_question
from kernel_v4.finance_score import load_gold_annotations, score_run_payload
from kernel_v4.loop import SingleAgentLoopConfig
from kernel_v4.monitoring import WorkflowConsoleMonitor
from kernel_v4.providers import DeepSeekChatProvider, ProviderAvailability

_SPLITS: dict[str, tuple[int, int | None, bool]] = {
    "debug50": (0, 50, False),
    "test100": (50, 100, True),
    "all150": (0, 150, False),
}


def load_jsonl_rows(path: str | Path) -> list[JsonObject]:
    rows: list[JsonObject] = []
    for line_number, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        decoded = json.loads(line)
        if not isinstance(decoded, dict):
            raise ValueError(f"{path}:{line_number} is not a JSON object")
        rows.append(decoded)
    return rows


def resolve_eval_slice(
    *,
    split: str,
    start_index: int | None,
    limit: int | None,
    row_count: int,
) -> tuple[int, int]:
    if split not in _SPLITS:
        raise ValueError(f"unknown split={split}; expected one of {sorted(_SPLITS)}")
    split_start, split_limit, _ = _SPLITS[split]
    resolved_start = split_start if start_index is None else int(start_index)
    if resolved_start < 0:
        raise ValueError("--start-index must be non-negative")
    resolved_limit = split_limit if limit is None else int(limit)
    if resolved_limit is None:
        resolved_limit = max(0, row_count - resolved_start)
    if resolved_limit <= 0:
        raise ValueError("--limit must be positive")
    if resolved_start >= row_count:
        raise IndexError(f"start index {resolved_start} out of range; rows={row_count}")
    available = row_count - resolved_start
    return resolved_start, min(resolved_limit, available)


async def run_finance_eval_rows(
    *,
    rows: Sequence[Mapping[str, Any]],
    annotations: Mapping[str, JsonObject],
    split: str,
    start_index: int,
    row_offsets: Sequence[int] | None = None,
    output_dir: str | Path,
    benchmark_family: str | None = "financebench",
    source_policy: str = "public_filings_or_provided_context",
    provided_context_format: str | None = None,
    model: ModelClient,
    provider_summary: JsonObject,
    allow_network: bool = True,
    config: SingleAgentLoopConfig | None = None,
    show_workflow: bool = False,
    workflow_format: str = "compact",
    include_score_details_in_summary: bool = False,
    item_timeout_seconds: float | None = None,
    run_id: str | None = None,
    include_transcript: bool = False,
    transcript_max_chars: int = 2_000,
    include_events: bool = False,
    item_run_retries: int = 0,
) -> JsonObject:
    out_dir = Path(output_dir)
    items_dir = out_dir / "items"
    items_dir.mkdir(parents=True, exist_ok=True)
    run_id = run_id or _default_run_id(split)
    config = config or SingleAgentLoopConfig(
        finance_mode=True,
        max_turns=64,
        max_tool_calls=200,
        max_tool_result_chars=12_000,
        model_context_mode="off",
    )
    items: list[JsonObject] = []
    completed_count = passed_count = run_failed_count = blocked_count = 0
    score_setup_failures = 0
    gold_in_context_count = 0

    for relative_index, row in enumerate(rows):
        offset = int(row_offsets[relative_index]) if row_offsets is not None else start_index + relative_index
        spec = FinanceQuestionSpec.from_mapping(
            row,
            benchmark_family=benchmark_family,
            source_policy=source_policy,
            provided_context_format=provided_context_format,
        )
        item_id = spec.task_id or f"offset_{offset}"
        safe_item = _safe_slug(item_id)
        item_run_id = f"{run_id}-o{offset:03d}"
        run_path = items_dir / f"{offset:03d}_{safe_item}.run.json"
        score_path = items_dir / f"{offset:03d}_{safe_item}.score.json"
        item_started_at = time.monotonic()
        result, retry_info = await _run_one_with_retries(
            spec=spec,
            model=model,
            allow_network=allow_network,
            config=config,
            thread_key=f"{split}:{item_id}",
            run_id=item_run_id,
            workflow_event_handler=WorkflowConsoleMonitor(mode=workflow_format) if show_workflow else None,
            item_timeout_seconds=item_timeout_seconds,
            item_run_retries=item_run_retries,
        )
        duration_seconds = time.monotonic() - item_started_at
        payload = _run_payload(
            result=result,
            spec=spec,
            provider_summary=provider_summary,
            split=split,
            offset=offset,
            run_id=item_run_id,
            duration_seconds=duration_seconds,
            include_transcript=include_transcript,
            transcript_max_chars=transcript_max_chars,
            include_events=include_events,
            retry_info=retry_info,
        )
        _write_json(run_path, payload)
        if payload.get("gold_reference_material_included"):
            gold_in_context_count += 1
        score = _score_payload(item_id=item_id, payload=payload, annotations=annotations)
        if score.get("status") == "failed":
            score_setup_failures += 1
        _write_json(score_path, score)
        item = _redacted_item_summary(
            offset=offset,
            item_id=item_id,
            payload=payload,
            score=score,
            run_path=run_path,
            score_path=score_path,
            include_score_details=include_score_details_in_summary,
        )
        items.append(item)
        if payload.get("status") == "completed":
            completed_count += 1
        elif payload.get("status") == "blocked":
            blocked_count += 1
        else:
            run_failed_count += 1
        if item.get("passed") is True:
            passed_count += 1
        print(json.dumps(_progress_event(item), ensure_ascii=False, sort_keys=True), flush=True)

    item_count = len(items)
    pass_rate = passed_count / item_count if item_count else 0.0
    failed_count = max(0, item_count - passed_count - blocked_count)
    summary: JsonObject = {
        "schema": "holo.kernel_v4.finance_live_eval_summary.v1",
        "status": "completed" if item_count and gold_in_context_count == 0 else "failed",
        "run_id": run_id,
        "split": split,
        "split_policy": _split_policy(split),
        "start_index": start_index,
        "item_count": item_count,
        "completed_count": completed_count,
        "failed_count": failed_count,
        "run_failed_count": run_failed_count,
        "blocked_count": blocked_count,
        "passed_count": passed_count,
        "pass_rate": pass_rate,
        "score_setup_failures": score_setup_failures,
        "gold_reference_material_used_for_scoring_only": True,
        "gold_reference_material_in_model_context": bool(gold_in_context_count),
        "capability_claim": False,
        "held_out_test_score": _SPLITS.get(split, (0, None, False))[2],
        "debug_tuning_score": split == "debug50",
        "provider": provider_summary,
        "usage_summary": _aggregate_usage(items),
        "cost_summary": _aggregate_cost(items),
        "experiment_metrics": _experiment_metrics(items),
        "failure_reasons": _failure_reason_counts(items),
        "items": items,
    }
    if row_offsets is not None:
        summary["row_offsets"] = [int(offset) for offset in row_offsets]
    _write_jsonl(out_dir / "items.jsonl", items)
    _write_items_csv(out_dir / "items.csv", items)
    _write_json(out_dir / "summary.json", summary)
    return summary


async def run_finance_eval_cli(args: argparse.Namespace) -> JsonObject:
    rows_all = load_jsonl_rows(args.row_jsonl)
    row_offsets = _parse_indices(args.indices, row_count=len(rows_all)) if args.indices else None
    if row_offsets is not None:
        selected_rows = [rows_all[offset] for offset in row_offsets]
        start_index = row_offsets[0]
        limit = len(selected_rows)
    else:
        start_index, limit = resolve_eval_slice(
            split=args.split,
            start_index=args.start_index,
            limit=args.limit,
            row_count=len(rows_all),
        )
        selected_rows = rows_all[start_index : start_index + limit]
    annotations = load_gold_annotations(args.gold_jsonl)
    provider = DeepSeekChatProvider(
        model=args.model,
        timeout_seconds=args.timeout_seconds,
        max_retries=args.max_retries,
        tool_choice=args.tool_choice,
        thinking=args.thinking,
        reasoning_effort=args.reasoning_effort,
    )
    availability = provider.availability()
    provider_summary = availability.to_dict()
    if not availability.available:
        return _blocked_summary(args=args, availability=availability, start_index=start_index, limit=limit)
    return await run_finance_eval_rows(
        rows=selected_rows,
        annotations=annotations,
        split=args.split,
        start_index=start_index,
        row_offsets=row_offsets,
        output_dir=args.output_dir or _default_output_dir(args.split),
        benchmark_family=args.benchmark_family,
        source_policy=args.source_policy,
        provided_context_format=args.provided_context_format,
        model=provider,
        provider_summary=provider_summary,
        allow_network=args.allow_network,
        config=SingleAgentLoopConfig(
            finance_mode=True,
            max_turns=args.max_turns,
            max_tool_calls=args.max_tool_calls,
            max_tool_result_chars=args.max_tool_result_chars,
            model_context_mode=args.model_context_mode,
        ),
        show_workflow=args.show_workflow,
        workflow_format=args.workflow_format,
        include_score_details_in_summary=args.include_score_details,
        item_timeout_seconds=args.item_timeout_seconds,
        run_id=args.run_id,
        include_transcript=args.include_transcript,
        transcript_max_chars=args.transcript_max_chars,
        include_events=args.include_events,
        item_run_retries=args.item_run_retries,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run Kernel v4 live finance debug/test batches with no-gold model context.")
    parser.add_argument("--row-jsonl", required=True, help="Benchmark row JSONL. Rows may contain gold fields; they are stripped from model context.")
    parser.add_argument("--gold-jsonl", required=True, help="Gold sidecar used only after each live run for scoring.")
    parser.add_argument("--split", default="debug50", choices=sorted(_SPLITS))
    parser.add_argument("--start-index", type=int, default=None, help="Override split start index for small probes.")
    parser.add_argument("--limit", type=int, default=None, help="Override split item count for small probes.")
    parser.add_argument("--indices", default=None, help="Comma-separated absolute row offsets to run; overrides --start-index/--limit for sparse debug batches.")
    parser.add_argument("--benchmark-family", default="financebench")
    parser.add_argument("--source-policy", default="public_filings_or_provided_context")
    parser.add_argument("--provided-context-format", default=None)
    parser.add_argument("--allow-network", action="store_true")
    parser.add_argument("--model", default=None)
    parser.add_argument("--timeout-seconds", type=int, default=120)
    parser.add_argument(
        "--item-timeout-seconds",
        type=float,
        default=1_200.0,
        help="Hard wall-clock timeout for one benchmark item; use 0 to disable for a long diagnostic run.",
    )
    parser.add_argument("--max-retries", type=int, default=1)
    parser.add_argument(
        "--item-run-retries",
        type=int,
        default=0,
        help=(
            "Retry a benchmark item from scratch after transient provider transport failures. "
            "Does not retry wrong completed answers or scoring failures."
        ),
    )
    parser.add_argument("--max-turns", type=int, default=64)
    parser.add_argument("--max-tool-calls", type=int, default=200)
    parser.add_argument("--max-tool-result-chars", type=int, default=12_000)
    parser.add_argument("--model-context-mode", default="off", choices=["off", "compact", "full"])
    parser.add_argument("--thinking", default=None, choices=["enabled", "disabled"])
    parser.add_argument("--reasoning-effort", default=None, choices=["low", "medium", "high", "max"])
    parser.add_argument("--tool-choice", default="auto", choices=["auto", "none", "required"])
    parser.add_argument("--show-workflow", action="store_true")
    parser.add_argument("--workflow-format", default="compact", choices=["compact", "jsonl"])
    parser.add_argument("--include-score-details", action="store_true", help="Include full scorer details in summary; default summary is gold-redacted.")
    parser.add_argument("--include-transcript", action="store_true", help="Include bounded message previews in each run JSON for paper trace analysis.")
    parser.add_argument("--transcript-max-chars", type=int, default=2_000)
    parser.add_argument("--include-events", action="store_true", help="Include raw loop events in each run JSON for paper trace analysis.")
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--output-dir", default=None)
    parser.add_argument("--summary-output", default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        payload = asyncio.run(run_finance_eval_cli(args))
    except Exception as exc:  # noqa: BLE001 - batch runner should return setup failures as JSON.
        payload = {
            "schema": "holo.kernel_v4.finance_live_eval_summary.v1",
            "status": "failed",
            "reason": f"setup_error:{type(exc).__name__}:{str(exc)[:500]}",
            "capability_claim": False,
            "gold_reference_material_in_model_context": False,
        }
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    if args.summary_output:
        Path(args.summary_output).write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0 if payload.get("status") == "completed" else 1


def _run_payload(
    *,
    result: LoopResult,
    spec: FinanceQuestionSpec,
    provider_summary: JsonObject,
    split: str,
    offset: int,
    run_id: str,
    duration_seconds: float,
    include_transcript: bool = False,
    transcript_max_chars: int = 2_000,
    include_events: bool = False,
    retry_info: JsonObject | None = None,
) -> JsonObject:
    payload: JsonObject = {
        "schema": "holo.kernel_v4.finance_run_result.v1",
        "status": result.status,
        "reason": result.reason,
        "run_id": run_id,
        "split": split,
        "offset": offset,
        "provider": provider_summary.get("provider"),
        "model": provider_summary.get("model"),
        "task": {
            "task_id": spec.task_id,
            "benchmark_family": spec.benchmark_family,
            "source_policy": spec.source_policy,
            "question_chars": len(spec.question),
            "provided_context_chars": len(spec.provided_context or ""),
            "safe_metadata_keys": sorted(spec.metadata.keys()),
            "excluded_gold_reference_field_count": len(spec.excluded_gold_reference_fields),
        },
        "answer": result.answer,
        "turn_count": result.turn_count,
        "tool_call_count": result.tool_call_count,
        "duration_seconds": duration_seconds,
        "event_count": len(result.events),
        "tool_trace_summary": _tool_trace_summary(result),
        "usage_summary": _usage_summary(result),
        "gold_reference_material_included": False,
        "capability_claim": False,
    }
    if retry_info:
        payload["retry_info"] = retry_info
    if include_transcript:
        payload["transcript"] = _transcript_preview(result, max_chars=transcript_max_chars)
    if include_events:
        payload["events"] = [event.__dict__ for event in result.events]
    return payload


async def _run_one_with_retries(
    *,
    spec: FinanceQuestionSpec,
    model: ModelClient,
    allow_network: bool,
    config: SingleAgentLoopConfig,
    thread_key: str,
    run_id: str,
    workflow_event_handler: Any,
    item_timeout_seconds: float | None,
    item_run_retries: int,
) -> tuple[LoopResult, JsonObject]:
    attempts: list[JsonObject] = []
    max_attempts = max(1, int(item_run_retries) + 1)
    for attempt_index in range(max_attempts):
        attempt_number = attempt_index + 1
        attempt_run_id = run_id if attempt_index == 0 else f"{run_id}-retry{attempt_index}"
        result = await _run_one_with_boundary(
            spec=spec,
            model=model,
            allow_network=allow_network,
            config=config,
            thread_key=thread_key,
            run_id=attempt_run_id,
            workflow_event_handler=workflow_event_handler,
            item_timeout_seconds=item_timeout_seconds,
        )
        retryable = _retryable_item_failure(result)
        attempts.append(
            {
                "attempt": attempt_number,
                "run_id": attempt_run_id,
                "status": result.status,
                "reason": result.reason,
                "turn_count": result.turn_count,
                "tool_call_count": result.tool_call_count,
                "retryable_transport_failure": retryable,
            }
        )
        if not retryable or attempt_number >= max_attempts:
            return result, _retry_info(max_attempts=max_attempts, attempts=attempts)
    return result, _retry_info(max_attempts=max_attempts, attempts=attempts)


async def _run_one_with_boundary(
    *,
    spec: FinanceQuestionSpec,
    model: ModelClient,
    allow_network: bool,
    config: SingleAgentLoopConfig,
    thread_key: str,
    run_id: str,
    workflow_event_handler: Any,
    item_timeout_seconds: float | None,
) -> LoopResult:
    recorder = _WorkflowEventRecorder(sink=workflow_event_handler)
    try:
        coroutine = run_finance_question(
            spec,
            model=model,
            allow_network=allow_network,
            config=config,
            thread_key=thread_key,
            run_id=run_id,
            workflow_event_handler=recorder,
        )
        if item_timeout_seconds is None or item_timeout_seconds <= 0:
            return await coroutine
        return await asyncio.wait_for(coroutine, timeout=float(item_timeout_seconds))
    except TimeoutError:
        return LoopResult(
            status="failed",
            answer="",
            messages=(),
            events=tuple(recorder.events),
            reason=f"item_timeout:{float(item_timeout_seconds):.1f}s",
            tool_call_count=recorder.tool_call_count,
            turn_count=recorder.turn_count,
        )
    except Exception as exc:  # noqa: BLE001 - one bad row must not kill a batch run.
        return LoopResult(
            status="failed",
            answer="",
            messages=(),
            events=tuple(recorder.events),
            reason=f"item_error:{type(exc).__name__}:{str(exc)[:300]}",
            tool_call_count=recorder.tool_call_count,
            turn_count=recorder.turn_count,
        )


def _retry_info(*, max_attempts: int, attempts: Sequence[JsonObject]) -> JsonObject:
    return {
        "schema": "holo.kernel_v4.item_run_retry_info.v1",
        "max_attempts": max_attempts,
        "attempt_count": len(attempts),
        "retry_count": max(0, len(attempts) - 1),
        "attempts": list(attempts),
    }


def _retryable_item_failure(result: LoopResult) -> bool:
    if result.status != "failed":
        return False
    reason = (result.reason or "").lower()
    if not reason:
        return False
    if "model_stream_error" not in reason and "item_error" not in reason:
        return False
    return any(
        marker in reason
        for marker in (
            "http 429",
            "http 500",
            "http 502",
            "http 503",
            "http 504",
            "network error",
            "ssl:",
            "unexpected_eof",
            "timeout",
            "timed out",
            "incompleteread",
            "remote disconnected",
            "remotedisconnected",
            "connection reset",
        )
    )


class _WorkflowEventRecorder:
    def __init__(self, *, sink: Any = None) -> None:
        self.sink = sink
        self.events: list[LoopEvent] = []

    def __call__(self, event: LoopEvent) -> None:
        self.events.append(event)
        if self.sink is not None:
            self.sink(event)

    @property
    def tool_call_count(self) -> int:
        return sum(1 for event in self.events if event.event_type == "assistant_tool_call")

    @property
    def turn_count(self) -> int:
        turn_indexes = [event.turn_index for event in self.events if event.turn_index > 0]
        return max(turn_indexes, default=0)


def _score_payload(*, item_id: str, payload: JsonObject, annotations: Mapping[str, JsonObject]) -> JsonObject:
    annotation = annotations.get(item_id)
    if annotation is None:
        return {
            "schema": "holo.kernel_v4.finance_score.v1",
            "status": "failed",
            "reason": "missing_gold_annotation",
            "item_id": item_id,
            "capability_claim": False,
            "gold_reference_material_used_for_scoring_only": True,
            "gold_reference_material_in_model_context": bool(payload.get("gold_reference_material_included")),
        }
    return score_run_payload(payload, annotation)


def _tool_trace_summary(result: LoopResult) -> JsonObject:
    calls: dict[str, JsonObject] = {}
    order: list[str] = []
    for event in result.events:
        if event.event_type == "assistant_tool_call":
            call_id = str(event.data.get("tool_call_id") or "")
            if not call_id:
                continue
            if call_id not in calls:
                calls[call_id] = {
                    "tool_call_id": call_id,
                    "tool": event.data.get("tool"),
                    "turn_index": event.turn_index,
                    "status": "called",
                    "is_error": None,
                }
                order.append(call_id)
            else:
                calls[call_id]["tool"] = calls[call_id].get("tool") or event.data.get("tool")
        elif event.event_type == "tool_result":
            call_id = str(event.data.get("tool_call_id") or "")
            if not call_id:
                continue
            row = calls.setdefault(
                call_id,
                {
                    "tool_call_id": call_id,
                    "tool": event.data.get("tool"),
                    "turn_index": event.turn_index,
                    "status": "called",
                    "is_error": None,
                },
            )
            if call_id not in order:
                order.append(call_id)
            row["tool"] = row.get("tool") or event.data.get("tool")
            row["status"] = "error" if event.data.get("is_error") else "ok"
            row["is_error"] = bool(event.data.get("is_error"))
            if event.data.get("artifact_id"):
                row["artifact_id"] = event.data.get("artifact_id")
    sequence = [calls[call_id] for call_id in order]
    by_tool: dict[str, int] = {}
    error_tools: dict[str, int] = {}
    for row in sequence:
        tool = str(row.get("tool") or "unknown")
        by_tool[tool] = by_tool.get(tool, 0) + 1
        if row.get("is_error") is True:
            error_tools[tool] = error_tools.get(tool, 0) + 1
    return {
        "schema": "holo.kernel_v4.tool_trace_summary.v1",
        "call_count": len(sequence),
        "by_tool": dict(sorted(by_tool.items())),
        "error_tools": dict(sorted(error_tools.items())),
        "sequence": sequence[:120],
        "truncated": len(sequence) > 120,
    }


def _redacted_item_summary(
    *,
    offset: int,
    item_id: str,
    payload: JsonObject,
    score: JsonObject,
    run_path: Path,
    score_path: Path,
    include_score_details: bool,
) -> JsonObject:
    score_payload = score.get("score") if isinstance(score.get("score"), dict) else score
    item: JsonObject = {
        "offset": offset,
        "item_id": item_id,
        "run_status": payload.get("status"),
        "run_reason": payload.get("reason"),
        "passed": score_payload.get("passed") if isinstance(score_payload, dict) else False,
        "score_reason": score_payload.get("reason") if isinstance(score_payload, dict) else score.get("reason"),
        "numeric_scored_count": score_payload.get("numeric_scored_count") if isinstance(score_payload, dict) else 0,
        "numeric_hit_count": score_payload.get("numeric_hit_count") if isinstance(score_payload, dict) else 0,
        "turn_count": payload.get("turn_count"),
        "tool_call_count": payload.get("tool_call_count"),
        "duration_seconds": payload.get("duration_seconds"),
        "usage_summary": payload.get("usage_summary", {}),
        "gold_reference_material_in_model_context": bool(payload.get("gold_reference_material_included")),
        "run_output": str(run_path),
        "score_output": str(score_path),
    }
    cost = estimate_deepseek_cost_usd(
        payload.get("usage_summary", {}),
        provider=payload.get("provider"),
        model=payload.get("model"),
    )
    if cost:
        item["cost_estimate"] = cost
    retry_info = payload.get("retry_info") if isinstance(payload.get("retry_info"), dict) else None
    if retry_info:
        item["item_run_retry_count"] = retry_info.get("retry_count", 0)
        item["item_run_attempt_count"] = retry_info.get("attempt_count", 1)
        attempts = retry_info.get("attempts") if isinstance(retry_info.get("attempts"), list) else []
        item["item_run_attempt_reasons"] = [
            attempt.get("reason")
            for attempt in attempts
            if isinstance(attempt, dict) and attempt.get("reason")
        ][:5]
    if include_score_details:
        item["score_details"] = score
    return item


def _progress_event(item: JsonObject) -> JsonObject:
    return {
        "event": "finance_eval_item_completed",
        "offset": item.get("offset"),
        "item_id": item.get("item_id"),
        "run_status": item.get("run_status"),
        "passed": item.get("passed"),
        "score_reason": item.get("score_reason"),
        "turn_count": item.get("turn_count"),
        "tool_call_count": item.get("tool_call_count"),
        "duration_seconds": item.get("duration_seconds"),
        "item_run_retry_count": item.get("item_run_retry_count", 0),
    }


def _aggregate_usage(items: Sequence[JsonObject]) -> JsonObject:
    summary: JsonObject = {
        "schema": "holo.kernel_v4.eval_usage_summary.v1",
        "items_with_usage": 0,
        "cache_hit_rate_available": False,
    }
    fields = (
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
        "prompt_cache_hit_tokens",
        "prompt_cache_miss_tokens",
        "cached_tokens",
    )
    totals = {field: 0 for field in fields}
    seen = {field: False for field in fields}
    for item in items:
        usage = item.get("usage_summary") if isinstance(item.get("usage_summary"), dict) else {}
        if not usage:
            continue
        summary["items_with_usage"] += 1
        for field in fields:
            value = usage.get(field)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                totals[field] += int(value)
                seen[field] = True
    for field in fields:
        if seen[field]:
            summary[field] = totals[field]
    hit = totals["prompt_cache_hit_tokens"]
    miss = totals["prompt_cache_miss_tokens"]
    if seen["prompt_cache_hit_tokens"] and seen["prompt_cache_miss_tokens"] and hit + miss > 0:
        summary["cache_hit_rate"] = hit / (hit + miss)
        summary["cache_hit_rate_available"] = True
    return summary


def _aggregate_cost(items: Sequence[JsonObject]) -> JsonObject:
    rows = [item.get("cost_estimate") for item in items if isinstance(item.get("cost_estimate"), dict)]
    summary: JsonObject = {
        "schema": "holo.kernel_v4.eval_cost_summary.v1",
        "items_with_cost": len(rows),
        "currency": "USD",
    }
    if not rows:
        return summary
    totals = {
        "input_cache_hit_usd": 0.0,
        "input_cache_miss_usd": 0.0,
        "output_usd": 0.0,
        "total_usd": 0.0,
    }
    tokens = {
        "input_cache_hit": 0,
        "input_cache_miss": 0,
        "output": 0,
    }
    families: dict[str, int] = {}
    pricing_sources: dict[str, int] = {}
    for row in rows:
        for field in totals:
            totals[field] += _numeric(row.get(field))
        token_row = row.get("tokens") if isinstance(row.get("tokens"), dict) else {}
        for field in tokens:
            tokens[field] += int(_numeric(token_row.get(field)))
        family = str(row.get("model_pricing_family") or "unknown")
        families[family] = families.get(family, 0) + 1
        source = str(row.get("pricing_source") or "unknown")
        pricing_sources[source] = pricing_sources.get(source, 0) + 1
    summary.update(totals)
    summary["tokens"] = tokens
    summary["model_pricing_families"] = dict(sorted(families.items()))
    summary["pricing_sources"] = dict(sorted(pricing_sources.items()))
    return summary


def _experiment_metrics(items: Sequence[JsonObject]) -> JsonObject:
    rows = list(items)
    tokens = [_numeric(item.get("usage_summary", {}).get("total_tokens")) for item in rows if isinstance(item.get("usage_summary"), dict)]
    prompt_tokens = [_numeric(item.get("usage_summary", {}).get("prompt_tokens")) for item in rows if isinstance(item.get("usage_summary"), dict)]
    completion_tokens = [
        _numeric(item.get("usage_summary", {}).get("completion_tokens")) for item in rows if isinstance(item.get("usage_summary"), dict)
    ]
    turns = [_numeric(item.get("turn_count")) for item in rows]
    tool_calls = [_numeric(item.get("tool_call_count")) for item in rows]
    durations = [_numeric(item.get("duration_seconds")) for item in rows]
    costs = [
        _numeric(item.get("cost_estimate", {}).get("total_usd"))
        for item in rows
        if isinstance(item.get("cost_estimate"), dict)
    ]
    cache_rates = [
        float(item["usage_summary"]["cache_hit_rate"])
        for item in rows
        if isinstance(item.get("usage_summary"), dict) and isinstance(item["usage_summary"].get("cache_hit_rate"), (int, float))
    ]
    return {
        "schema": "holo.kernel_v4.finance_eval_experiment_metrics.v1",
        "item_count": len(rows),
        "pass_rate": (sum(1 for item in rows if item.get("passed") is True) / len(rows)) if rows else 0.0,
        "turns": _distribution(turns),
        "tool_calls": _distribution(tool_calls),
        "duration_seconds": _distribution(durations),
        "total_tokens": _distribution(tokens),
        "prompt_tokens": _distribution(prompt_tokens),
        "completion_tokens": _distribution(completion_tokens),
        "cache_hit_rate": _distribution(cache_rates),
        "estimated_cost_usd": _distribution(costs),
        "high_cost_item_offsets": [
            item.get("offset")
            for item in rows
            if _numeric(item.get("usage_summary", {}).get("total_tokens") if isinstance(item.get("usage_summary"), dict) else None) >= 500_000
        ],
        "chart_files": {
            "items_csv": "items.csv",
            "items_jsonl": "items.jsonl",
        },
    }


def _distribution(values: Sequence[float | int]) -> JsonObject:
    clean = sorted(float(value) for value in values if isinstance(value, (int, float)) and not isinstance(value, bool))
    if not clean:
        return {"count": 0}
    return {
        "count": len(clean),
        "sum": sum(clean),
        "min": clean[0],
        "max": clean[-1],
        "mean": sum(clean) / len(clean),
        "median": _percentile(clean, 0.5),
        "p90": _percentile(clean, 0.9),
    }


def _percentile(sorted_values: Sequence[float], q: float) -> float:
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return sorted_values[0]
    position = (len(sorted_values) - 1) * q
    lower = int(position)
    upper = min(lower + 1, len(sorted_values) - 1)
    weight = position - lower
    return sorted_values[lower] * (1 - weight) + sorted_values[upper] * weight


def _numeric(value: object) -> float:
    if isinstance(value, bool):
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    return 0.0


def _failure_reason_counts(items: Sequence[JsonObject]) -> JsonObject:
    counts: dict[str, int] = {}
    for item in items:
        if item.get("passed") is True:
            continue
        reason = str(item.get("score_reason") or item.get("run_reason") or "unknown")
        counts[reason] = counts.get(reason, 0) + 1
    return dict(sorted(counts.items(), key=lambda row: (-row[1], row[0])))


def _blocked_summary(*, args: argparse.Namespace, availability: ProviderAvailability, start_index: int, limit: int) -> JsonObject:
    return {
        "schema": "holo.kernel_v4.finance_live_eval_summary.v1",
        "status": "blocked",
        "reason": availability.reason,
        "split": args.split,
        "start_index": start_index,
        "item_count": limit,
        "provider": availability.to_dict(),
        "gold_reference_material_in_model_context": False,
        "capability_claim": False,
    }


def _parse_indices(value: str, *, row_count: int) -> list[int]:
    offsets: list[int] = []
    seen: set[int] = set()
    for raw in str(value or "").split(","):
        item = raw.strip()
        if not item:
            continue
        try:
            offset = int(item)
        except ValueError as exc:
            raise ValueError(f"--indices entries must be integers; got {item!r}") from exc
        if offset < 0 or offset >= row_count:
            raise IndexError(f"--indices offset {offset} out of range; rows={row_count}")
        if offset in seen:
            continue
        seen.add(offset)
        offsets.append(offset)
    if not offsets:
        raise ValueError("--indices must include at least one offset")
    return offsets


def _split_policy(split: str) -> str:
    if split == "test100":
        return "held-out FinanceBench offsets 50-149; do not tune against item-level failures from this run."
    if split == "debug50":
        return "debug/tuning FinanceBench offsets 0-49; failures may be inspected for generic loop/tool improvements."
    return "full local 150-row diagnostic; not a held-out score if used for tuning."


def _default_output_dir(split: str) -> str:
    return f".state/kernel_v4/bench/finance/{_default_run_id(split)}"


def _default_run_id(split: str) -> str:
    return f"fb_{split}_live_{time.strftime('%Y%m%d_%H%M%S')}"


def _safe_slug(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("._")
    return slug[:80] or "item"


def _write_json(path: Path, payload: JsonObject) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, rows: Sequence[JsonObject]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows), encoding="utf-8")


def _write_items_csv(path: Path, rows: Sequence[JsonObject]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "offset",
        "item_id",
        "passed",
        "run_status",
        "score_reason",
        "numeric_scored_count",
        "numeric_hit_count",
        "turn_count",
        "tool_call_count",
        "total_tokens",
        "prompt_tokens",
        "completion_tokens",
        "prompt_cache_hit_tokens",
        "prompt_cache_miss_tokens",
        "cache_hit_rate",
        "duration_seconds",
        "estimated_cost_usd",
        "run_output",
        "score_output",
    ]
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for item in rows:
            usage = item.get("usage_summary") if isinstance(item.get("usage_summary"), dict) else {}
            cost = item.get("cost_estimate") if isinstance(item.get("cost_estimate"), dict) else {}
            writer.writerow(
                {
                    "offset": item.get("offset"),
                    "item_id": item.get("item_id"),
                    "passed": item.get("passed"),
                    "run_status": item.get("run_status"),
                    "score_reason": item.get("score_reason"),
                    "numeric_scored_count": item.get("numeric_scored_count"),
                    "numeric_hit_count": item.get("numeric_hit_count"),
                    "turn_count": item.get("turn_count"),
                    "tool_call_count": item.get("tool_call_count"),
                    "total_tokens": usage.get("total_tokens"),
                    "prompt_tokens": usage.get("prompt_tokens"),
                    "completion_tokens": usage.get("completion_tokens"),
                    "prompt_cache_hit_tokens": usage.get("prompt_cache_hit_tokens"),
                    "prompt_cache_miss_tokens": usage.get("prompt_cache_miss_tokens"),
                    "cache_hit_rate": usage.get("cache_hit_rate"),
                    "duration_seconds": item.get("duration_seconds"),
                    "estimated_cost_usd": cost.get("total_usd"),
                    "run_output": item.get("run_output"),
                    "score_output": item.get("score_output"),
                }
            )


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
