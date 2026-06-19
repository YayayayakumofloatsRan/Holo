from __future__ import annotations

import argparse
import asyncio
import json
import sys

from kernel_v4.finance_run import _usage_summary
from kernel_v4.finance_tools import register_calculator_tool_surface, register_finance_tool_surface
from kernel_v4.loop import SingleAgentLoop, SingleAgentLoopConfig
from kernel_v4.monitoring import WorkflowConsoleMonitor
from kernel_v4.providers import DeepSeekChatProvider
from kernel_v4.tooling import ToolRegistry


DEFAULT_PROMPT = "Reply exactly with: v4 live provider ok. Do not call tools."


async def run_live_smoke(args: argparse.Namespace) -> dict[str, object]:
    provider = DeepSeekChatProvider(
        model=args.model,
        timeout_seconds=args.timeout_seconds,
        max_retries=args.max_retries,
        tool_choice=args.tool_choice,
        force_tool_name=args.force_tool,
        force_tool_turns=args.force_tool_turns,
        thinking=args.thinking,
        reasoning_effort=args.reasoning_effort,
    )
    availability = provider.availability()
    if not availability.available:
        return {
            "status": "blocked",
            "reason": availability.reason,
            "provider": availability.provider,
            "model": availability.model,
        }
    registry = ToolRegistry()
    if args.calculator_only:
        register_calculator_tool_surface(registry)
    elif args.finance_tools:
        register_finance_tool_surface(registry, allow_network=args.allow_network)
    loop = SingleAgentLoop(
        model=provider,
        tools=registry,
        config=SingleAgentLoopConfig(
            max_turns=args.max_turns,
            max_tool_calls=args.max_tool_calls,
            finance_mode=args.finance_tools,
            model_context_mode=args.model_context_mode,
        ),
    )
    result = await loop.run(
        args.prompt,
        thread_key="kernel-v4-live-smoke",
        workflow_event_handler=WorkflowConsoleMonitor(mode=args.workflow_format) if args.show_workflow else None,
    )
    return {
        "status": result.status,
        "reason": result.reason,
        "provider": provider.name,
        "model": provider.model,
        "answer": result.answer,
        "turn_count": result.turn_count,
        "tool_call_count": result.tool_call_count,
        "event_count": len(result.events),
        "usage_summary": _usage_summary(result),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Kernel v4 live provider smoke.")
    parser.add_argument("--model", default=None)
    parser.add_argument("--prompt", default=DEFAULT_PROMPT)
    parser.add_argument("--timeout-seconds", type=int, default=90)
    parser.add_argument("--max-retries", type=int, default=1)
    parser.add_argument("--max-turns", type=int, default=4)
    parser.add_argument("--max-tool-calls", type=int, default=12)
    parser.add_argument("--model-context-mode", default="full", choices=["off", "compact", "full"])
    parser.add_argument("--thinking", default=None, choices=["enabled", "disabled"])
    parser.add_argument("--reasoning-effort", default=None, choices=["low", "medium", "high", "max"])
    parser.add_argument("--tool-choice", default="auto", choices=["auto", "none", "required"])
    parser.add_argument(
        "--force-tool",
        default=None,
        help="Force a visible v4 tool name through provider-native tool_choice.",
    )
    parser.add_argument(
        "--force-tool-turns",
        type=int,
        default=1,
        help="Number of initial model turns that should force --force-tool.",
    )
    parser.add_argument("--finance-tools", action="store_true")
    parser.add_argument("--calculator-only", action="store_true", help="Expose only calculator.compute plus v4 core tools.")
    parser.add_argument("--allow-network", action="store_true")
    parser.add_argument("--show-workflow", action="store_true", help="Print live workflow events to stderr.")
    parser.add_argument(
        "--workflow-format",
        default="compact",
        choices=["compact", "jsonl"],
        help="Workflow event display format for --show-workflow.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    payload = asyncio.run(run_live_smoke(args))
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 0 if payload.get("status") == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
