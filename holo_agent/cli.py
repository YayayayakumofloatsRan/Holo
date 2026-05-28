from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from . import __version__
from .agent import AgentConfig, HoloAgent
from .event_log import sanitize
from .memory import MemoryStore
from .model import DeepSeekJsonModel, RuleFallbackModel
from .tools import ToolRegistry
from .workspace import load_workspace_context


RETRY_FOLLOWUP_TEXT = {
    "再试一次",
    "重试",
    "再试试",
    "我说去查一下",
    "去查一下",
    "？？？",
    "???",
    "?",
    "？",
    "try again",
    "retry",
}


def _agent(args: argparse.Namespace) -> HoloAgent:
    requested_model = str(getattr(args, "model", "") or "auto")
    if requested_model == "auto":
        model_name = "deepseek-chat" if os.environ.get("DEEPSEEK_API_KEY") else "fallback"
    else:
        model_name = requested_model
    model = DeepSeekJsonModel(model=model_name) if model_name != "fallback" else RuleFallbackModel()
    return HoloAgent(
        tools=ToolRegistry.default(root=Path.cwd(), source_evaluator=model),
        model=model,
        config=AgentConfig(
            max_steps=int(getattr(args, "max_steps", 10) or 10),
            log_path=Path(getattr(args, "log", ".holo_kernel/events.jsonl")),
            model_name=model_name,
            workspace_root=Path.cwd(),
        ),
    )


def render_trace(result: dict[str, Any]) -> str:
    lines: list[str] = []
    for event in result.get("events", []):
        kind = event.get("kind", "")
        message = event.get("message", "")
        if kind == "final":
            continue
        lines.append(f"[{kind}] {message}".rstrip())
    lines.append("[final]")
    lines.append(str(result.get("final", "")))
    return "\n".join(lines)


class ChatSession:
    def __init__(self, agent: HoloAgent) -> None:
        self.agent = agent
        self.last_goal_text = ""
        self.last_stop_reason = ""
        self.last_status = ""

    def _effective_text(self, text: str) -> str:
        stripped = str(text or "").strip()
        if stripped.lower() in RETRY_FOLLOWUP_TEXT and self.last_goal_text and self.last_stop_reason in {
            "tool_failure_report",
            "evidence_exhausted",
            "budget_exhausted",
        }:
            return self.last_goal_text
        return stripped

    def run_turn(self, text: str):
        raw_text = str(text or "").strip()
        effective_text = self._effective_text(raw_text)
        result = self.agent.run(effective_text)
        result.metadata["raw_user_text"] = raw_text
        result.metadata["effective_user_text"] = effective_text
        result.metadata["inherited_goal"] = effective_text != raw_text
        if effective_text:
            self.last_goal_text = effective_text
        self.last_stop_reason = result.stop_reason
        self.last_status = result.status
        return result


def command_run(args: argparse.Namespace) -> int:
    result = _agent(args).run(str(args.prompt or ""))
    payload = sanitize(result.to_dict())
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    elif args.trace:
        print(render_trace(payload))
    else:
        print(payload["final"])
    return 0 if payload["status"] == "ok" else 1


def command_chat(args: argparse.Namespace) -> int:
    agent = _agent(args)
    session = ChatSession(agent)
    print(f"Holo Agent Kernel {__version__} | /exit to quit")
    while True:
        try:
            line = input("holo-agent> ")
        except EOFError:
            print()
            return 0
        text = line.strip()
        if not text:
            continue
        if text in {"/exit", "/quit"}:
            return 0
        if text == "/status":
            workspace = load_workspace_context(Path.cwd())
            print(f"kernel={__version__} instructions={len(workspace.instruction_layers)} skills={len(workspace.skills)}")
            continue
        if text == "/skills":
            workspace = load_workspace_context(Path.cwd())
            if not workspace.skills:
                print("no skills loaded")
            else:
                for skill in workspace.skills:
                    print(f"- {skill.name}: {skill.description}")
            continue
        if text == "/memory":
            memory = MemoryStore(Path(".holo_kernel/memory.json")).snapshot()
            print(json.dumps(sanitize(memory), ensure_ascii=False, indent=2))
            continue
        if text == "/web":
            print(json.dumps(sanitize(agent.tools.web_provider_health()), ensure_ascii=False, indent=2))
            continue
        if text == "/logs":
            log_path = Path(getattr(args, "log", ".holo_kernel/events.jsonl"))
            if not log_path.exists():
                print("no log file")
            else:
                rows = log_path.read_text(encoding="utf-8").splitlines()[-10:]
                print("\n".join(rows))
            continue
        result = sanitize(session.run_turn(text).to_dict())
        print(render_trace(result) if args.trace else result["final"])


def command_status(args: argparse.Namespace) -> int:
    workspace = load_workspace_context(Path.cwd())
    tools = ToolRegistry.default(root=Path.cwd())
    payload = {
        "kernel_version": __version__,
        "workspace": workspace.to_dict(),
        "log": str(Path(getattr(args, "log", ".holo_kernel/events.jsonl"))),
        "web_provider_health": tools.web_provider_health(),
    }
    print(json.dumps(sanitize(payload), ensure_ascii=False, indent=2))
    return 0


def command_memory(args: argparse.Namespace) -> int:
    store = MemoryStore(Path(".holo_kernel/memory.json"))
    if args.set:
        key, _, value = args.set.partition("=")
        store.set_preference(key.strip(), value.strip())
    if args.note:
        store.add_note(args.note)
    print(json.dumps(sanitize(store.snapshot()), ensure_ascii=False, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="holo-agent")
    parser.add_argument("--model", default="auto", help="auto, fallback, or a DeepSeek model name such as deepseek-chat")
    parser.add_argument("--max-steps", type=int, default=10)
    parser.add_argument("--log", default=".holo_kernel/events.jsonl")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="run one agent task")
    run.add_argument("prompt")
    run.add_argument("--trace", action="store_true")
    run.add_argument("--json", action="store_true")
    run.add_argument("--model", default=argparse.SUPPRESS)
    run.add_argument("--max-steps", type=int, default=argparse.SUPPRESS)
    run.add_argument("--log", default=argparse.SUPPRESS)
    run.set_defaults(func=command_run)

    chat = sub.add_parser("chat", help="interactive agent console")
    chat.add_argument("--trace", action="store_true")
    chat.add_argument("--model", default=argparse.SUPPRESS)
    chat.add_argument("--max-steps", type=int, default=argparse.SUPPRESS)
    chat.add_argument("--log", default=argparse.SUPPRESS)
    chat.set_defaults(func=command_chat)

    status = sub.add_parser("status", help="inspect kernel workspace context")
    status.add_argument("--log", default=".holo_kernel/events.jsonl")
    status.set_defaults(func=command_status)

    memory = sub.add_parser("memory", help="inspect or update local kernel memory")
    memory.add_argument("--set", default="", help="set preference key=value")
    memory.add_argument("--note", default="", help="append a memory note")
    memory.set_defaults(func=command_memory)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))
