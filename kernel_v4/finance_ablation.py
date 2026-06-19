from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from kernel_v4.contracts import JsonObject
from kernel_v4.finance_eval import (
    _aggregate_usage,
    _aggregate_cost,
    _distribution,
    _experiment_metrics,
    _failure_reason_counts,
    _write_json,
    _write_jsonl,
)
from kernel_v4.finance_repeat import run_repeat_cli


async def run_ablation_cli(args: argparse.Namespace) -> JsonObject:
    conditions = _load_conditions(args.conditions_json)
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    all_items: list[JsonObject] = []
    condition_summaries: list[JsonObject] = []
    for index, condition in enumerate(conditions, start=1):
        condition_id = _condition_id(condition, index=index)
        condition_dir = out_dir / condition_id
        repeat_args = argparse.Namespace(
            row_jsonl=args.row_jsonl,
            gold_jsonl=args.gold_jsonl,
            split=args.split,
            start_index=args.start_index,
            limit=1,
            repeats=int(condition.get("repeats", args.repeats)),
            benchmark_family=args.benchmark_family,
            source_policy=args.source_policy,
            provided_context_format=args.provided_context_format,
            allow_network=args.allow_network,
            model=str(condition.get("model") or args.model or ""),
            timeout_seconds=args.timeout_seconds,
            item_timeout_seconds=args.item_timeout_seconds,
            max_retries=args.max_retries,
            max_turns=int(condition.get("max_turns", args.max_turns)),
            max_tool_calls=int(condition.get("max_tool_calls", args.max_tool_calls)),
            max_tool_result_chars=int(condition.get("max_tool_result_chars", args.max_tool_result_chars)),
            model_context_mode=str(condition.get("model_context_mode") or args.model_context_mode),
            thinking=condition.get("thinking", args.thinking),
            reasoning_effort=condition.get("reasoning_effort", args.reasoning_effort),
            tool_choice=str(condition.get("tool_choice") or args.tool_choice),
            show_workflow=args.show_workflow,
            workflow_format=args.workflow_format,
            include_score_details=args.include_score_details,
            include_transcript=getattr(args, "include_transcript", False),
            transcript_max_chars=getattr(args, "transcript_max_chars", 2_000),
            include_events=getattr(args, "include_events", False),
            run_id=f"{args.run_id}_{condition_id}" if args.run_id else condition_id,
            output_dir=str(condition_dir),
        )
        summary = await run_repeat_cli(repeat_args)
        items = [dict(item) for item in summary.get("items", []) if isinstance(item, dict)]
        for item in items:
            item["condition_id"] = condition_id
            item["condition_index"] = index
            item["condition"] = {
                "model": repeat_args.model,
                "thinking": repeat_args.thinking,
                "reasoning_effort": repeat_args.reasoning_effort,
                "model_context_mode": repeat_args.model_context_mode,
                "max_turns": repeat_args.max_turns,
                "max_tool_calls": repeat_args.max_tool_calls,
            }
        all_items.extend(items)
        condition_summary = _condition_summary(
            condition_id=condition_id,
            condition_index=index,
            condition=items[0].get("condition") if items else {},
            output_dir=condition_dir,
            summary=summary,
        )
        condition_summaries.append(condition_summary)
        print(
            json.dumps(
                {
                    "event": "finance_ablation_condition_completed",
                    "condition_id": condition_id,
                    "condition_index": index,
                    "condition_count": len(conditions),
                    "pass_rate": condition_summary.get("pass_rate"),
                    "replicate_count": condition_summary.get("replicate_count"),
                    "turns": condition_summary.get("turns"),
                    "tool_calls": condition_summary.get("tool_calls"),
                    "cache_hit_rate": condition_summary.get("cache_hit_rate"),
                    "output_dir": str(condition_dir),
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            flush=True,
        )

    summary = {
        "schema": "holo.kernel_v4.finance_ablation_experiment.v1",
        "status": "completed" if all_items else "failed",
        "run_id": args.run_id,
        "split": args.split,
        "start_index": args.start_index,
        "condition_count": len(conditions),
        "replicate_count": len(all_items),
        "provider_family": "deepseek",
        "gold_reference_material_used_for_scoring_only": True,
        "gold_reference_material_in_model_context": any(bool(item.get("gold_reference_material_in_model_context")) for item in all_items),
        "capability_claim": False,
        "debug_tuning_score": args.split == "debug50",
        "held_out_test_score": args.split == "test100",
        "pass_rate": (sum(1 for item in all_items if item.get("passed") is True) / len(all_items)) if all_items else 0.0,
        "usage_summary": _aggregate_usage(all_items),
        "cost_summary": _aggregate_cost(all_items),
        "experiment_metrics": _experiment_metrics(all_items),
        "failure_reasons": _failure_reason_counts(all_items),
        "conditions": condition_summaries,
        "items": all_items,
    }
    _write_json(out_dir / "ablation_summary.json", summary)
    _write_jsonl(out_dir / "ablation_items.jsonl", all_items)
    return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a no-gold live finance ablation matrix for one benchmark item.")
    parser.add_argument("--row-jsonl", required=True)
    parser.add_argument("--gold-jsonl", required=True)
    parser.add_argument("--conditions-json", required=True, help="JSON array of condition objects.")
    parser.add_argument("--split", default="debug50", choices=["all150", "debug50", "test100"])
    parser.add_argument("--start-index", type=int, required=True)
    parser.add_argument("--repeats", type=int, default=3)
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
    parser.add_argument("--output-dir", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        summary = asyncio.run(run_ablation_cli(args))
    except Exception as exc:  # noqa: BLE001
        summary = {
            "schema": "holo.kernel_v4.finance_ablation_experiment.v1",
            "status": "failed",
            "reason": f"setup_error:{type(exc).__name__}:{str(exc)[:500]}",
            "capability_claim": False,
            "gold_reference_material_in_model_context": False,
        }
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0 if summary.get("status") == "completed" else 1


def _load_conditions(path: str) -> list[JsonObject]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, list) or not raw:
        raise ValueError("conditions-json must contain a non-empty JSON array")
    return [dict(item) for item in raw if isinstance(item, dict)]


def _condition_id(condition: JsonObject, *, index: int) -> str:
    if condition.get("id"):
        return _safe_slug(str(condition["id"]))
    model = _safe_slug(str(condition.get("model") or "model"))
    thinking = _safe_slug(str(condition.get("thinking") or "default"))
    effort = _safe_slug(str(condition.get("reasoning_effort") or "none"))
    return f"c{index:02d}_{model}_{thinking}_{effort}"


def _safe_slug(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in value).strip("._")[:80] or "condition"


def _condition_summary(
    *,
    condition_id: str,
    condition_index: int,
    condition: object,
    output_dir: Path,
    summary: JsonObject,
) -> JsonObject:
    items = [dict(item) for item in summary.get("items", []) if isinstance(item, dict)]
    turns = [item.get("turn_count") for item in items]
    tool_calls = [item.get("tool_call_count") for item in items]
    cache_rates = [
        item["usage_summary"]["cache_hit_rate"]
        for item in items
        if isinstance(item.get("usage_summary"), dict) and isinstance(item["usage_summary"].get("cache_hit_rate"), (int, float))
    ]
    total_tokens = [
        item["usage_summary"]["total_tokens"]
        for item in items
        if isinstance(item.get("usage_summary"), dict) and isinstance(item["usage_summary"].get("total_tokens"), (int, float))
    ]
    durations = [item.get("duration_seconds") for item in items]
    costs = [
        item["cost_estimate"]["total_usd"]
        for item in items
        if isinstance(item.get("cost_estimate"), dict) and isinstance(item["cost_estimate"].get("total_usd"), (int, float))
    ]
    return {
        "condition_id": condition_id,
        "condition_index": condition_index,
        "condition": condition if isinstance(condition, dict) else {},
        "output_dir": str(output_dir),
        "replicate_count": len(items),
        "pass_rate": summary.get("pass_rate"),
        "passed_count": summary.get("passed_count"),
        "turns": _distribution(turns),
        "tool_calls": _distribution(tool_calls),
        "duration_seconds": _distribution(durations),
        "cache_hit_rate": _distribution(cache_rates),
        "total_tokens": _distribution(total_tokens),
        "estimated_cost_usd": _distribution(costs),
        "cost_summary": summary.get("cost_summary", {}),
        "failure_reasons": summary.get("failure_reasons", {}),
    }


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
