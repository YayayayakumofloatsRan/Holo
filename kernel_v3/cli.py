from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from kernel_v3.context import ContextCompiler, ContextPackCompiler
from kernel_v3.journal import JournalStore
from kernel_v3.loop import LoopControllerV3
from kernel_v3.policy import PolicyGate
from kernel_v3.testing.fakes import FakeEvaluator, FakePlanner
from kernel_v3.tools import ToolRegistry
from kernel_v3.trace import TraceRenderer


def main(argv: list[str] | None = None) -> int:
    argv = _normalize_argv(list(sys.argv[1:] if argv is None else argv))
    parser = argparse.ArgumentParser(prog="holo-v3")
    parser.add_argument("--journal", default="kernel_v3/.holo-v3-journal.jsonl")
    parser.add_argument("--index", default="kernel_v3/.holo-v3-journal.sqlite")
    sub = parser.add_subparsers(dest="command", required=True)

    run_parser = sub.add_parser("run")
    run_parser.add_argument("text")

    trace_parser = sub.add_parser("trace")
    trace_parser.add_argument("task_id")

    resume_parser = sub.add_parser("resume")
    resume_parser.add_argument("task_id")
    resume_parser.add_argument("text")

    context_parser = sub.add_parser("context")
    context_sub = context_parser.add_subparsers(dest="context_command")
    context_dump = context_sub.add_parser("dump")
    context_dump.add_argument("task_id")
    context_sections = context_sub.add_parser("sections")
    context_sections.add_argument("task_id")
    context_artifacts = context_sub.add_parser("artifacts")
    context_artifacts.add_argument("task_id")
    context_parser.add_argument("legacy_task_id", nargs="?")

    sub.add_parser("tools")

    journal_parser = sub.add_parser("journal")
    journal_sub = journal_parser.add_subparsers(dest="journal_command", required=True)
    journal_sub.add_parser("tail")

    args = parser.parse_args(argv)
    journal = JournalStore(Path(args.journal), index_path=Path(args.index))

    if args.command == "run":
        result = _loop(journal, answer=f"respond: {args.text}").run(args.text)
        print(json.dumps(result.__dict__, ensure_ascii=False, sort_keys=True))
        return 0

    if args.command == "resume":
        result = _loop(journal, answer=f"resumed: {args.text}").resume(args.task_id, user_input=args.text)
        print(json.dumps(result.__dict__, ensure_ascii=False, sort_keys=True))
        return 0

    if args.command == "trace":
        print(TraceRenderer(journal).render_task(args.task_id))
        return 0

    if args.command == "context":
        task_id = args.legacy_task_id or getattr(args, "task_id", None)
        if task_id is None:
            parser.error("context requires a task_id or a context subcommand")
        state = _active_task(journal, task_id)
        pack = ContextPackCompiler(permission_state={"mode": "read_write"}).compile(
            state,
            journal,
            tool_briefs=_tool_briefs(),
            step_id=state.step_id,
        )
        if args.context_command == "sections":
            print(json.dumps([section["name"] for section in pack.sections], ensure_ascii=False, sort_keys=True))
            return 0
        if args.context_command == "artifacts":
            artifacts = next(section for section in pack.sections if section["name"] == "artifact_references")
            print(json.dumps(artifacts["artifacts"], ensure_ascii=False, sort_keys=True))
            return 0
        print(json.dumps(pack.to_dict(), ensure_ascii=False, sort_keys=True))
        return 0

    if args.command == "tools":
        print("\n".join(tool["name"] for tool in _tool_briefs()))
        return 0

    if args.command == "journal" and args.journal_command == "tail":
        for record in journal.records()[-10:]:
            print(json.dumps(record.to_dict(), ensure_ascii=False, sort_keys=True))
        return 0

    raise AssertionError(f"unhandled command: {args.command}")


def _normalize_argv(argv: list[str]) -> list[str]:
    if "context" not in argv:
        return argv
    try:
        index = argv.index("context")
    except ValueError:
        return argv
    if index + 1 >= len(argv):
        return argv
    next_token = argv[index + 1]
    if next_token in {"dump", "sections", "artifacts"} or next_token.startswith("-"):
        return argv
    return argv[: index + 1] + ["dump"] + argv[index + 1 :]


def _loop(journal: JournalStore, *, answer: str) -> LoopControllerV3:
    return LoopControllerV3(
        journal=journal,
        context_compiler=ContextCompiler(),
        planner=FakePlanner.respond_once(answer),
        policy_gate=PolicyGate(permission="read_write"),
        tool_registry=ToolRegistry.with_fake_workspace_tools(files={"README.md": "Holo local kernel"}),
        evaluator=FakeEvaluator.final_answer(answer),
    )


def _active_task(journal: JournalStore, task_id: str):
    from kernel_v3.session import SessionEngine

    return SessionEngine.from_journal(journal).active_task(task_id)


def _tool_briefs() -> list[dict[str, str]]:
    return [
        {"name": "respond", "side_effect": "none"},
        {"name": "ask_user", "side_effect": "none"},
        {"name": "workspace.search", "side_effect": "read"},
        {"name": "file.read", "side_effect": "read"},
        {"name": "blocked_external_write", "side_effect": "destructive"},
    ]


if __name__ == "__main__":
    raise SystemExit(main())
