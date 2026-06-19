from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

from kernel_v4.contracts import JsonObject
from kernel_v4.finance_eval import (
    _aggregate_usage,
    _aggregate_cost,
    _default_run_id,
    _distribution,
    _experiment_metrics,
    _failure_reason_counts,
    _write_items_csv,
    _write_json,
    _write_jsonl,
    load_jsonl_rows,
    resolve_eval_slice,
    run_finance_eval_rows,
)
from kernel_v4.finance_score import load_gold_annotations
from kernel_v4.loop import SingleAgentLoopConfig
from kernel_v4.providers import DeepSeekChatProvider


async def run_repeat_cli(args: argparse.Namespace) -> JsonObject:
    rows_all = load_jsonl_rows(args.row_jsonl)
    start_index, limit = resolve_eval_slice(
        split=args.split,
        start_index=args.start_index,
        limit=args.limit,
        row_count=len(rows_all),
    )
    if limit != 1:
        raise ValueError("finance_repeat currently requires --limit 1 so each replicate is the same task")
    row = rows_all[start_index]
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
    run_id = args.run_id or f"{_default_run_id(args.split)}_repeat_o{start_index:03d}_n{args.repeats:02d}"
    out_dir = Path(args.output_dir or f".state/kernel_v4/bench/finance/{run_id}")
    out_dir.mkdir(parents=True, exist_ok=True)
    if not availability.available:
        summary = {
            "schema": "holo.kernel_v4.finance_repeat_experiment.v1",
            "status": "blocked",
            "reason": availability.reason,
            "provider": provider_summary,
            "capability_claim": False,
            "gold_reference_material_in_model_context": False,
        }
        _write_json(out_dir / "repeat_summary.json", summary)
        return summary

    aggregate_items: list[JsonObject] = []
    replicate_summaries: list[JsonObject] = []
    for replicate_index in range(1, args.repeats + 1):
        replicate_run_id = f"{run_id}_r{replicate_index:02d}"
        replicate_dir = out_dir / f"replicate_{replicate_index:02d}"
        summary = await run_finance_eval_rows(
            rows=[row],
            annotations=annotations,
            split=args.split,
            start_index=start_index,
            output_dir=replicate_dir,
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
            run_id=replicate_run_id,
            include_transcript=getattr(args, "include_transcript", False),
            transcript_max_chars=getattr(args, "transcript_max_chars", 2_000),
            include_events=getattr(args, "include_events", False),
        )
        item = dict(summary.get("items", [{}])[0])
        item["replicate_index"] = replicate_index
        item["replicate_run_id"] = replicate_run_id
        item["replicate_output_dir"] = str(replicate_dir)
        aggregate_items.append(item)
        replicate_summaries.append(
            {
                "replicate_index": replicate_index,
                "run_id": replicate_run_id,
                "output_dir": str(replicate_dir),
                "passed": item.get("passed"),
                "score_reason": item.get("score_reason"),
                "run_status": item.get("run_status"),
                "turn_count": item.get("turn_count"),
                "tool_call_count": item.get("tool_call_count"),
                "duration_seconds": item.get("duration_seconds"),
                "usage_summary": item.get("usage_summary", {}),
                "cost_estimate": item.get("cost_estimate", {}),
            }
        )
        print(
            json.dumps(
                {
                    "event": "finance_repeat_replicate_completed",
                    "replicate_index": replicate_index,
                    "replicate_count": args.repeats,
                    "run_id": replicate_run_id,
                    "passed": item.get("passed"),
                    "score_reason": item.get("score_reason"),
                    "turn_count": item.get("turn_count"),
                    "tool_call_count": item.get("tool_call_count"),
                    "duration_seconds": item.get("duration_seconds"),
                    "cache_hit_rate": (item.get("usage_summary") or {}).get("cache_hit_rate")
                    if isinstance(item.get("usage_summary"), dict)
                    else None,
                    "total_tokens": (item.get("usage_summary") or {}).get("total_tokens")
                    if isinstance(item.get("usage_summary"), dict)
                    else None,
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            flush=True,
        )

    pass_count = sum(1 for item in aggregate_items if item.get("passed") is True)
    status = "completed" if aggregate_items and not any(item.get("gold_reference_material_in_model_context") for item in aggregate_items) else "failed"
    summary = {
        "schema": "holo.kernel_v4.finance_repeat_experiment.v1",
        "status": status,
        "run_id": run_id,
        "split": args.split,
        "start_index": start_index,
        "limit": limit,
        "replicate_count": args.repeats,
        "passed_count": pass_count,
        "pass_rate": pass_count / len(aggregate_items) if aggregate_items else 0.0,
        "provider": provider_summary,
        "model_context_mode": args.model_context_mode,
        "gold_reference_material_used_for_scoring_only": True,
        "gold_reference_material_in_model_context": any(
            bool(item.get("gold_reference_material_in_model_context")) for item in aggregate_items
        ),
        "capability_claim": False,
        "debug_tuning_score": args.split == "debug50",
        "held_out_test_score": args.split == "test100",
        "usage_summary": _aggregate_usage(aggregate_items),
        "cost_summary": _aggregate_cost(aggregate_items),
        "experiment_metrics": _experiment_metrics(aggregate_items),
        "failure_reasons": _failure_reason_counts(aggregate_items),
        "answer_length_chars": _distribution([_answer_length(item) for item in aggregate_items]),
        "replicates": replicate_summaries,
        "items": aggregate_items,
    }
    _write_json(out_dir / "repeat_summary.json", summary)
    _write_jsonl(out_dir / "repeat_items.jsonl", aggregate_items)
    _write_items_csv(out_dir / "repeat_items.csv", aggregate_items)
    return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Repeat one no-gold live finance task for stability/cost experiments.")
    parser.add_argument("--row-jsonl", required=True)
    parser.add_argument("--gold-jsonl", required=True)
    parser.add_argument("--split", default="debug50", choices=["all150", "debug50", "test100"])
    parser.add_argument("--start-index", type=int, required=True)
    parser.add_argument("--limit", type=int, default=1)
    parser.add_argument("--repeats", type=int, default=10)
    parser.add_argument("--benchmark-family", default="financebench")
    parser.add_argument("--source-policy", default="public_filings_or_provided_context")
    parser.add_argument("--provided-context-format", default=None)
    parser.add_argument("--allow-network", action="store_true")
    parser.add_argument("--model", default=None)
    parser.add_argument("--timeout-seconds", type=int, default=120)
    parser.add_argument("--item-timeout-seconds", type=float, default=1_200.0)
    parser.add_argument("--max-retries", type=int, default=1)
    parser.add_argument("--max-turns", type=int, default=96)
    parser.add_argument("--max-tool-calls", type=int, default=260)
    parser.add_argument("--max-tool-result-chars", type=int, default=12_000)
    parser.add_argument("--model-context-mode", default="off", choices=["off", "compact", "full"])
    parser.add_argument("--thinking", default=None, choices=["enabled", "disabled"])
    parser.add_argument("--reasoning-effort", default=None, choices=["low", "medium", "high", "max"])
    parser.add_argument("--tool-choice", default="auto", choices=["auto", "none", "required"])
    parser.add_argument("--show-workflow", action="store_true")
    parser.add_argument("--workflow-format", default="compact", choices=["compact", "jsonl"])
    parser.add_argument("--include-score-details", action="store_true")
    parser.add_argument("--include-transcript", action="store_true", help="Include bounded message previews in each replicate run JSON.")
    parser.add_argument("--transcript-max-chars", type=int, default=2_000)
    parser.add_argument("--include-events", action="store_true", help="Include raw loop events in each replicate run JSON.")
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--output-dir", default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        summary = asyncio.run(run_repeat_cli(args))
    except Exception as exc:  # noqa: BLE001 - repeat runner should emit JSON on setup failure.
        summary = {
            "schema": "holo.kernel_v4.finance_repeat_experiment.v1",
            "status": "failed",
            "reason": f"setup_error:{type(exc).__name__}:{str(exc)[:500]}",
            "capability_claim": False,
            "gold_reference_material_in_model_context": False,
        }
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0 if summary.get("status") == "completed" else 1


def _answer_length(item: JsonObject) -> int:
    run_output = item.get("run_output")
    if not isinstance(run_output, str):
        return 0
    path = Path(run_output)
    if not path.exists():
        return 0
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 0
    answer = payload.get("answer")
    return len(answer) if isinstance(answer, str) else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
