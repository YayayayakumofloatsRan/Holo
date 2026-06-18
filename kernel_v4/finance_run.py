from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

from kernel_v4.finance_runner import FinanceQuestionSpec, run_finance_question
from kernel_v4.loop import SingleAgentLoopConfig
from kernel_v4.monitoring import WorkflowConsoleMonitor
from kernel_v4.providers import DeepSeekChatProvider


def load_row_from_args(args: argparse.Namespace) -> dict[str, Any]:
    sources = [bool(args.row_json), bool(args.row_file), bool(args.row_jsonl)]
    if sum(sources) != 1:
        raise ValueError("provide exactly one of --row-json, --row-file, or --row-jsonl")
    if args.row_json:
        row = json.loads(args.row_json)
        if not isinstance(row, dict):
            raise ValueError("--row-json must decode to an object")
        return row
    if args.row_file:
        raw = Path(args.row_file).read_text(encoding="utf-8")
        decoded = json.loads(raw)
        if isinstance(decoded, dict):
            return dict(decoded)
        if isinstance(decoded, list):
            return _row_at_index(decoded, args.index, source=str(args.row_file))
        raise ValueError("--row-file must contain a JSON object or list of objects")
    rows = []
    for line in Path(args.row_jsonl).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        decoded = json.loads(line)
        if not isinstance(decoded, dict):
            raise ValueError("--row-jsonl must contain one JSON object per line")
        rows.append(decoded)
    return _row_at_index(rows, args.index, source=str(args.row_jsonl))


def _row_at_index(rows: list[Any], index: int, *, source: str) -> dict[str, Any]:
    if index < 0 or index >= len(rows):
        raise IndexError(f"row index {index} out of range for {source}; rows={len(rows)}")
    row = rows[index]
    if not isinstance(row, dict):
        raise ValueError(f"row index {index} in {source} is not a JSON object")
    return dict(row)


async def run_finance_cli(args: argparse.Namespace) -> dict[str, Any]:
    row = load_row_from_args(args)
    spec = FinanceQuestionSpec.from_mapping(
        row,
        benchmark_family=args.benchmark_family,
        source_policy=args.source_policy,
        provided_context_format=args.provided_context_format,
    )
    if args.dry_run:
        return _dry_run_payload(spec)

    provider = DeepSeekChatProvider(
        model=args.model,
        timeout_seconds=args.timeout_seconds,
        max_retries=args.max_retries,
        tool_choice=args.tool_choice,
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
            item["metadata"] = message.metadata
        rows.append(item)
    return rows


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run one no-gold Kernel v4 finance task.")
    source = parser.add_argument_group("task input")
    source.add_argument("--row-json", default=None, help="One JSON object containing a finance task row.")
    source.add_argument("--row-file", default=None, help="Path to a JSON object or list of row objects.")
    source.add_argument("--row-jsonl", default=None, help="Path to a JSONL file with one row object per line.")
    source.add_argument("--index", type=int, default=0, help="Row index for --row-file lists or --row-jsonl.")

    parser.add_argument("--benchmark-family", default=None)
    parser.add_argument("--source-policy", default="public_filings_or_provided_context")
    parser.add_argument("--provided-context-format", default=None)
    parser.add_argument("--dry-run", action="store_true", help="Build the no-gold packet summary without calling a provider.")

    parser.add_argument("--model", default=None)
    parser.add_argument("--timeout-seconds", type=int, default=90)
    parser.add_argument("--max-retries", type=int, default=1)
    parser.add_argument("--max-turns", type=int, default=24)
    parser.add_argument("--max-tool-calls", type=int, default=80)
    parser.add_argument("--max-tool-result-chars", type=int, default=50_000)
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
    return 0 if payload.get("status") in {"completed", "dry_run"} else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
