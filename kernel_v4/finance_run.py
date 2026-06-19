from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

from kernel_v4.finance_runner import (
    FinanceQuestionSpec,
    audit_finance_question_closure,
    build_finance_registry,
    run_finance_question,
)
from kernel_v4.loop import SingleAgentLoopConfig
from kernel_v4.monitoring import WorkflowConsoleMonitor
from kernel_v4.providers import DeepSeekChatProvider


def load_row_from_args(args: argparse.Namespace) -> dict[str, Any]:
    rows = load_rows_from_args(args)
    return rows[0]


def load_rows_from_args(args: argparse.Namespace) -> list[dict[str, Any]]:
    sources = [bool(args.row_json), bool(args.row_file), bool(args.row_jsonl)]
    if sum(sources) != 1:
        raise ValueError("provide exactly one of --row-json, --row-file, or --row-jsonl")
    if args.row_json:
        if int(getattr(args, "limit", 1) or 1) != 1:
            raise ValueError("--row-json supports only --limit 1")
        row = json.loads(args.row_json)
        if not isinstance(row, dict):
            raise ValueError("--row-json must decode to an object")
        return [row]
    if args.row_file:
        raw = Path(args.row_file).read_text(encoding="utf-8")
        decoded = json.loads(raw)
        if isinstance(decoded, dict):
            return [dict(decoded)]
        if isinstance(decoded, list):
            return _rows_slice(decoded, args.index, args.limit, source=str(args.row_file))
        raise ValueError("--row-file must contain a JSON object or list of objects")
    rows = []
    for line in Path(args.row_jsonl).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        decoded = json.loads(line)
        if not isinstance(decoded, dict):
            raise ValueError("--row-jsonl must contain one JSON object per line")
        rows.append(decoded)
    return _rows_slice(rows, args.index, args.limit, source=str(args.row_jsonl))


def _row_at_index(rows: list[Any], index: int, *, source: str) -> dict[str, Any]:
    if index < 0 or index >= len(rows):
        raise IndexError(f"row index {index} out of range for {source}; rows={len(rows)}")
    row = rows[index]
    if not isinstance(row, dict):
        raise ValueError(f"row index {index} in {source} is not a JSON object")
    return dict(row)


def _rows_slice(rows: list[Any], index: int, limit: int, *, source: str) -> list[dict[str, Any]]:
    if limit <= 0:
        raise ValueError("--limit must be positive")
    selected = rows[index : index + limit]
    if not selected:
        raise IndexError(f"row index {index} out of range for {source}; rows={len(rows)}")
    return [_row_at_index(rows, item_index, source=source) for item_index in range(index, index + len(selected))]


async def run_finance_cli(args: argparse.Namespace) -> dict[str, Any]:
    if args.closure_audit and int(args.limit) != 1:
        rows = load_rows_from_args(args)
        return await _closure_audit_batch(args, rows)
    row = load_row_from_args(args)
    spec = FinanceQuestionSpec.from_mapping(
        row,
        benchmark_family=args.benchmark_family,
        source_policy=args.source_policy,
        provided_context_format=args.provided_context_format,
    )
    if args.dry_run:
        return _dry_run_payload(spec)
    if args.closure_audit:
        return await audit_finance_question_closure(spec, allow_network=args.allow_network)

    provider = DeepSeekChatProvider(
        model=args.model,
        timeout_seconds=args.timeout_seconds,
        max_retries=args.max_retries,
        tool_choice=args.tool_choice,
        thinking=args.thinking,
        reasoning_effort=args.reasoning_effort,
    )
    availability = provider.availability()
    if not availability.available:
        return {
            "schema": "holo.kernel_v4.finance_run_result.v1",
            "status": "blocked",
            "reason": availability.reason,
            "provider": availability.provider,
            "model": availability.model,
            "task": _task_summary(spec),
        }
    result = await run_finance_question(
        spec,
        model=provider,
        allow_network=args.allow_network,
        config=SingleAgentLoopConfig(
            finance_mode=True,
            max_turns=args.max_turns,
            max_tool_calls=args.max_tool_calls,
            max_tool_result_chars=args.max_tool_result_chars,
            model_context_mode=args.model_context_mode,
        ),
        thread_key=args.thread_key or spec.task_id or "kernel-v4-finance-run",
        workflow_event_handler=WorkflowConsoleMonitor(mode=args.workflow_format) if args.show_workflow else None,
    )
    return {
        "schema": "holo.kernel_v4.finance_run_result.v1",
        "status": result.status,
        "reason": result.reason,
        "provider": provider.name,
        "model": provider.model,
        "task": _task_summary(spec),
        "answer": result.answer,
        "turn_count": result.turn_count,
        "tool_call_count": result.tool_call_count,
        "event_count": len(result.events),
        "usage_summary": _usage_summary(result),
        "gold_reference_material_included": False,
        "capability_claim": False,
        **({"transcript": _transcript_preview(result, max_chars=args.transcript_max_chars)} if args.include_transcript else {}),
        **({"events": [event.__dict__ for event in result.events]} if args.include_events else {}),
    }


def _dry_run_payload(spec: FinanceQuestionSpec) -> dict[str, Any]:
    return {
        "schema": "holo.kernel_v4.finance_run_dry_run.v1",
        "status": "dry_run",
        "task": _task_summary(spec),
        "packet_preview": {
            "chars": len(spec.to_user_message()),
            "contains_gold_reference_material": False,
        },
        "gold_reference_material_included": False,
        "capability_claim": False,
    }


async def _closure_audit_batch(args: argparse.Namespace, rows: list[dict[str, Any]]) -> dict[str, Any]:
    registry = build_finance_registry(allow_network=args.allow_network)
    items: list[dict[str, Any]] = []
    ok_count = failed_count = 0
    for offset, row in enumerate(rows, start=int(args.index)):
        spec = FinanceQuestionSpec.from_mapping(
            row,
            benchmark_family=args.benchmark_family,
            source_policy=args.source_policy,
            provided_context_format=args.provided_context_format,
        )
        audit = await audit_finance_question_closure(spec, registry=registry, allow_network=args.allow_network)
        if audit.get("status") == "ok":
            ok_count += 1
        else:
            failed_count += 1
        items.append(
            {
                "index": offset,
                "task_id": audit.get("task", {}).get("task_id") if isinstance(audit.get("task"), dict) else None,
                "status": audit.get("status"),
                "audit_mode": audit.get("audit_mode"),
                "failure_reasons": audit.get("failure_reasons", []),
                "selected_profile_families": (
                    audit.get("workbench", {}).get("selected_profile_families", [])
                    if isinstance(audit.get("workbench"), dict)
                    else []
                ),
                "selected_missing_tools": (
                    audit.get("workbench", {}).get("selected_missing_tools", {})
                    if isinstance(audit.get("workbench"), dict)
                    else {}
                ),
                "excluded_gold_reference_field_count": (
                    audit.get("task", {}).get("excluded_gold_reference_field_count", 0)
                    if isinstance(audit.get("task"), dict)
                    else 0
                ),
            }
        )
    return {
        "schema": "holo.kernel_v4.finance_closure_audit_batch.v1",
        "status": "ok" if failed_count == 0 else "failed",
        "item_count": len(items),
        "ok_count": ok_count,
        "failed_count": failed_count,
        "start_index": int(args.index),
        "limit": int(args.limit),
        "allow_network": bool(args.allow_network),
        "items": items,
        "gold_reference_material_included": False,
        "capability_claim": False,
        "benchmark_progress_claim": False,
        "host_boundary": "Batch closure audit checks row-to-contract coverage only; it does not solve or score benchmark answers.",
    }


def _task_summary(spec: FinanceQuestionSpec) -> dict[str, Any]:
    return {
        "task_id": spec.task_id,
        "benchmark_family": spec.benchmark_family,
        "source_policy": spec.source_policy,
        "question_chars": len(spec.question),
        "provided_context_chars": len(spec.provided_context or ""),
        "safe_metadata_keys": sorted(spec.metadata.keys()),
        "excluded_gold_reference_field_count": len(spec.excluded_gold_reference_fields),
    }


def _transcript_preview(result: Any, *, max_chars: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    limit = max(200, min(int(max_chars), 20_000))
    for index, message in enumerate(result.messages):
        item: dict[str, Any] = {
            "index": index,
            "role": message.role,
            "chars": len(message.content),
            "content_preview": message.content[:limit],
        }
        if message.name:
            item["name"] = message.name
        if message.tool_call_id:
            item["tool_call_id"] = message.tool_call_id
        if message.tool_calls:
            item["tool_calls"] = [
                {"tool_call_id": call.tool_call_id, "name": call.name, "input": call.input}
                for call in message.tool_calls
            ]
        if message.metadata:
            item["metadata"] = {
                key: ("<redacted>" if key == "_private_reasoning_content" else value)
                for key, value in message.metadata.items()
            }
        rows.append(item)
    return rows


def _usage_summary(result: Any) -> dict[str, Any]:
    events = getattr(result, "events", ()) or ()
    usage_events = [
        event.data
        for event in events
        if getattr(event, "event_type", "") == "model_usage" and isinstance(getattr(event, "data", None), dict)
    ]
    summary: dict[str, Any] = {
        "schema": "holo.kernel_v4.usage_summary.v1",
        "model_usage_event_count": len(usage_events),
        "cache_hit_rate_available": False,
    }
    if not usage_events:
        return summary
    prompt_tokens = completion_tokens = total_tokens = 0
    hit_tokens = miss_tokens = cached_tokens = 0
    saw_prompt = saw_completion = saw_total = False
    saw_hit = saw_miss = saw_cached = False
    for usage in usage_events:
        if (value := _optional_int(usage.get("prompt_tokens") or usage.get("input_tokens"))) is not None:
            prompt_tokens += value
            saw_prompt = True
        if (value := _optional_int(usage.get("completion_tokens") or usage.get("output_tokens"))) is not None:
            completion_tokens += value
            saw_completion = True
        if (value := _optional_int(usage.get("total_tokens"))) is not None:
            total_tokens += value
            saw_total = True
        cache = usage.get("cache") if isinstance(usage.get("cache"), dict) else {}
        if (value := _optional_int(cache.get("prompt_cache_hit_tokens"))) is not None:
            hit_tokens += value
            saw_hit = True
        if (value := _optional_int(cache.get("prompt_cache_miss_tokens"))) is not None:
            miss_tokens += value
            saw_miss = True
        if (value := _optional_int(cache.get("cached_tokens"))) is not None:
            cached_tokens += value
            saw_cached = True
    if saw_prompt:
        summary["prompt_tokens"] = prompt_tokens
    if saw_completion:
        summary["completion_tokens"] = completion_tokens
    if saw_total:
        summary["total_tokens"] = total_tokens
    if saw_hit:
        summary["prompt_cache_hit_tokens"] = hit_tokens
    if saw_miss:
        summary["prompt_cache_miss_tokens"] = miss_tokens
    if saw_cached:
        summary["cached_tokens"] = cached_tokens
    denominator = None
    if saw_hit and saw_miss and hit_tokens + miss_tokens > 0:
        denominator = hit_tokens + miss_tokens
    elif saw_hit and saw_prompt and prompt_tokens > 0:
        denominator = prompt_tokens
    if denominator:
        summary["cache_hit_rate"] = hit_tokens / denominator
        summary["cache_hit_rate_available"] = True
    return summary


def _optional_int(value: object) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run one no-gold Kernel v4 finance task.")
    source = parser.add_argument_group("task input")
    source.add_argument("--row-json", default=None, help="One JSON object containing a finance task row.")
    source.add_argument("--row-file", default=None, help="Path to a JSON object or list of row objects.")
    source.add_argument("--row-jsonl", default=None, help="Path to a JSONL file with one row object per line.")
    source.add_argument("--index", type=int, default=0, help="Row index for --row-file lists or --row-jsonl.")
    source.add_argument("--limit", type=int, default=1, help="Number of rows for --closure-audit batch mode.")

    parser.add_argument("--benchmark-family", default=None)
    parser.add_argument("--source-policy", default="public_filings_or_provided_context")
    parser.add_argument("--provided-context-format", default=None)
    parser.add_argument("--dry-run", action="store_true", help="Build the no-gold packet summary without calling a provider.")
    parser.add_argument(
        "--closure-audit",
        action="store_true",
        help="Run no-provider row-to-workbench/toolchain closure audit without solving or scoring.",
    )

    parser.add_argument("--model", default=None)
    parser.add_argument("--timeout-seconds", type=int, default=90)
    parser.add_argument("--max-retries", type=int, default=1)
    parser.add_argument("--max-turns", type=int, default=64)
    parser.add_argument("--max-tool-calls", type=int, default=200)
    parser.add_argument("--max-tool-result-chars", type=int, default=12_000)
    parser.add_argument("--model-context-mode", default="off", choices=["off", "compact", "full"])
    parser.add_argument("--thinking", default=None, choices=["enabled", "disabled"])
    parser.add_argument("--reasoning-effort", default=None, choices=["low", "medium", "high", "max"])
    parser.add_argument("--tool-choice", default="auto", choices=["auto", "none", "required"])
    parser.add_argument("--allow-network", action="store_true")
    parser.add_argument("--thread-key", default=None)
    parser.add_argument("--show-workflow", action="store_true")
    parser.add_argument("--workflow-format", default="compact", choices=["compact", "jsonl"])
    parser.add_argument("--include-transcript", action="store_true", help="Include bounded message previews in JSON output.")
    parser.add_argument("--transcript-max-chars", type=int, default=2000)
    parser.add_argument("--include-events", action="store_true", help="Include raw loop events in JSON output.")
    parser.add_argument("--output", default=None, help="Optional JSON output path.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        payload = asyncio.run(run_finance_cli(args))
    except Exception as exc:  # noqa: BLE001 - CLI should report structured setup failures.
        payload = {
            "schema": "holo.kernel_v4.finance_run_result.v1",
            "status": "failed",
            "reason": f"setup_error:{type(exc).__name__}:{str(exc)[:500]}",
            "capability_claim": False,
            "gold_reference_material_included": False,
        }
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0 if payload.get("status") in {"completed", "dry_run", "ok"} else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
