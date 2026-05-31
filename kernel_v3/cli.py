from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from kernel_v3.agent import AgentRuntime, analyze_goal
from kernel_v3.chat import ChatRuntime
from kernel_v3.context import ContextCompiler, ContextPackCompiler
from kernel_v3.journal import JournalStore
from kernel_v3.loop import LoopControllerV3
from kernel_v3.memory import MemoryPipeline, MemoryStore
from kernel_v3.policy import PolicyGate
from kernel_v3.processors import (
    PLANNER_SCHEMA,
    PLANNER_PROMPT_CONTRACT,
    DeepSeekProvider,
    FakeJsonProvider,
    ModelPlanner,
    OpenAICompatibleProvider,
    ProcessorFabric,
    ProcessorRouter,
    Synthesizer,
    deepseek_v4_router,
    run_semantic_scenarios,
    scenario_report_payload,
)
from kernel_v3.retrieval import FakeFetchProvider, FakeSearchProvider, RetrievalOperator, SearchGoal, SearchSource
from kernel_v3.resident import ResidentQueue, ResidentRuntime
from kernel_v3.testing.fakes import FakeEvaluator, FakePlanner
from kernel_v3.tools import ToolRegistry
from kernel_v3.trace import TraceRenderer


def main(argv: list[str] | None = None) -> int:
    argv = _normalize_argv(list(sys.argv[1:] if argv is None else argv))
    parser = argparse.ArgumentParser(prog="holo-v3")
    parser.add_argument("--journal", default="kernel_v3/.holo-v3-journal.jsonl")
    parser.add_argument("--index", default="kernel_v3/.holo-v3-journal.sqlite")
    parser.add_argument("--memory-log", default=None)
    parser.add_argument("--memory-index", default=None)
    parser.add_argument("--resident-db", default=None)
    sub = parser.add_subparsers(dest="command", required=True)

    run_parser = sub.add_parser("run")
    run_parser.add_argument("--planner", choices=["fake", "model"], default="fake")
    run_parser.add_argument("text")

    agent_parser = sub.add_parser("agent")
    agent_parser.add_argument("goal")
    agent_parser.add_argument("--mode", choices=["direct", "retrieval", "workspace", "auto"], default="auto")
    agent_parser.add_argument("--planner", choices=["fake", "model"], default="fake")
    agent_parser.add_argument("--evaluator", choices=["fake", "model"], default="fake")
    agent_parser.add_argument("--synthesizer", choices=["fake", "model"], default="fake")
    agent_parser.add_argument("--semantic-intake", choices=["fake", "model"], default="fake")
    agent_parser.add_argument("--model", default=None)
    agent_parser.add_argument("--profile", choices=["fast", "balanced", "quality"], default="balanced")
    agent_parser.add_argument("--thinking", choices=["auto", "enabled", "disabled"], default="auto")
    agent_parser.add_argument("--reasoning-effort", choices=["high", "max"], default="high")
    agent_parser.add_argument("--citations-required", action="store_true")

    answer_parser = sub.add_parser("answer")
    answer_parser.add_argument("goal")
    answer_parser.add_argument("--citations-required", action="store_true")

    chat_parser = sub.add_parser("chat")
    chat_parser.add_argument("--thread", default="default")
    chat_parser.add_argument("--once", default=None)
    chat_parser.add_argument("--planner", choices=["fake", "model"], default="fake")
    chat_parser.add_argument("--evaluator", choices=["fake", "model"], default="fake")
    chat_parser.add_argument("--synthesizer", choices=["fake", "model"], default="fake")
    chat_parser.add_argument("--semantic-intake", choices=["fake", "model"], default="fake")
    chat_parser.add_argument("--model", default=None)
    chat_parser.add_argument("--profile", choices=["fast", "balanced", "quality"], default="balanced")
    chat_parser.add_argument("--thinking", choices=["auto", "enabled", "disabled"], default="auto")
    chat_parser.add_argument("--reasoning-effort", choices=["high", "max"], default="high")

    chat_status_parser = sub.add_parser("chat-status")
    chat_status_parser.add_argument("thread_id")

    chat_summary_parser = sub.add_parser("chat-summary")
    chat_summary_parser.add_argument("thread_id")

    memory_parser = sub.add_parser("memory")
    memory_sub = memory_parser.add_subparsers(dest="memory_command", required=True)
    memory_list = memory_sub.add_parser("list")
    memory_list.add_argument("--thread", default=None)
    memory_list.add_argument("--query", default=None)
    memory_proposals = memory_sub.add_parser("proposals")
    memory_proposals.add_argument("--thread", default=None)
    memory_propose = memory_sub.add_parser("propose")
    memory_propose.add_argument("text")
    memory_propose.add_argument("--thread", default="default")
    memory_approve = memory_sub.add_parser("approve")
    memory_approve.add_argument("proposal_id")
    memory_reject = memory_sub.add_parser("reject")
    memory_reject.add_argument("proposal_id")
    memory_reject.add_argument("--reason", default="user_rejected")
    memory_delete = memory_sub.add_parser("delete")
    memory_delete.add_argument("memory_id")
    memory_delete.add_argument("--reason", default="user_deleted")
    memory_export = memory_sub.add_parser("export")
    memory_export.add_argument("memory_id")
    memory_migrate = memory_sub.add_parser("migrate-semantic")
    memory_migrate.add_argument("--limit", type=int, default=None)

    resident_parser = sub.add_parser("resident")
    resident_sub = resident_parser.add_subparsers(dest="resident_command", required=True)
    resident_enqueue = resident_sub.add_parser("enqueue")
    resident_enqueue.add_argument("text")
    resident_enqueue.add_argument("--thread", default="default")
    resident_enqueue.add_argument("--message-id", default=None)
    resident_run_once = resident_sub.add_parser("run-once")
    resident_run_once.add_argument("--worker-id", default="resident-worker-1")
    resident_run_once.add_argument("--max-attempts", type=int, default=3)
    resident_run_once.add_argument("--retry-backoff-ms", type=int, default=1000)
    resident_run_once.add_argument("--planner", choices=["fake", "model"], default="fake")
    resident_run_once.add_argument("--evaluator", choices=["fake", "model"], default="fake")
    resident_run_once.add_argument("--synthesizer", choices=["fake", "model"], default="fake")
    resident_run_once.add_argument("--semantic-intake", choices=["fake", "model"], default="fake")
    resident_run_once.add_argument("--model", default=None)
    resident_run_once.add_argument("--profile", choices=["fast", "balanced", "quality"], default="balanced")
    resident_run_once.add_argument("--thinking", choices=["auto", "enabled", "disabled"], default="auto")
    resident_run_once.add_argument("--reasoning-effort", choices=["high", "max"], default="high")
    resident_run = resident_sub.add_parser("run")
    resident_run.add_argument("--worker-id", default="resident-worker-1")
    resident_run.add_argument("--max-iterations", type=int, default=10)
    resident_run.add_argument("--max-attempts", type=int, default=3)
    resident_run.add_argument("--retry-backoff-ms", type=int, default=1000)
    resident_run.add_argument("--planner", choices=["fake", "model"], default="fake")
    resident_run.add_argument("--evaluator", choices=["fake", "model"], default="fake")
    resident_run.add_argument("--synthesizer", choices=["fake", "model"], default="fake")
    resident_run.add_argument("--semantic-intake", choices=["fake", "model"], default="fake")
    resident_run.add_argument("--model", default=None)
    resident_run.add_argument("--profile", choices=["fast", "balanced", "quality"], default="balanced")
    resident_run.add_argument("--thinking", choices=["auto", "enabled", "disabled"], default="auto")
    resident_run.add_argument("--reasoning-effort", choices=["high", "max"], default="high")
    resident_sub.add_parser("status")
    resident_sub.add_parser("inbox")
    resident_sub.add_parser("outbox")
    resident_requeue = resident_sub.add_parser("requeue")
    resident_requeue.add_argument("message_id")
    resident_requeue.add_argument("--reason", default="manual_requeue")
    resident_requeue.add_argument("--keep-attempts", action="store_true")
    resident_ack = resident_sub.add_parser("ack")
    resident_ack.add_argument("outbox_id")
    resident_ack.add_argument("--status", default="acknowledged")

    inspect_run_parser = sub.add_parser("inspect-run")
    inspect_run_parser.add_argument("task_id")

    inspect_workloop_parser = sub.add_parser("inspect-workloop")
    inspect_workloop_parser.add_argument("task_id")

    final_answer_parser = sub.add_parser("final-answer")
    final_answer_parser.add_argument("task_id")

    failure_report_parser = sub.add_parser("failure-report")
    failure_report_parser.add_argument("task_id")

    retrieve_parser = sub.add_parser("retrieve")
    retrieve_parser.add_argument("query")
    retrieve_parser.add_argument("--synthesizer", choices=["fake", "model"], default="fake")
    retrieve_parser.add_argument("--body", default=None)

    trace_parser = sub.add_parser("trace")
    trace_parser.add_argument("task_id")
    trace_parser.add_argument("--verbose", action="store_true")

    evidence_parser = sub.add_parser("evidence")
    evidence_parser.add_argument("task_id")

    artifacts_parser = sub.add_parser("artifacts")
    artifacts_parser.add_argument("task_id")

    retrieval_trace_parser = sub.add_parser("retrieval-trace")
    retrieval_trace_parser.add_argument("task_id")

    memory_trace_parser = sub.add_parser("memory-trace")
    memory_trace_parser.add_argument("task_id")
    sub.add_parser("resident-trace")

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
    sub.add_parser("providers")

    provider_smoke = sub.add_parser("provider-smoke")
    provider_smoke.add_argument("--fake", action="store_true")

    model_smoke = sub.add_parser("model-smoke")
    model_smoke.add_argument("--provider", choices=["deepseek", "openai_compatible"], required=True)
    model_smoke.add_argument("--model", default=None)
    model_smoke.add_argument("--thinking", choices=["auto", "enabled", "disabled"], default="auto")
    model_smoke.add_argument("--reasoning-effort", choices=["high", "max"], default="high")

    model_scenarios = sub.add_parser("model-scenarios")
    model_scenarios.add_argument("--provider", choices=["deepseek", "openai_compatible"], required=True)
    model_scenarios.add_argument("--model", default=None)
    model_scenarios.add_argument("--profile", choices=["fast", "balanced", "quality"], default="balanced")
    model_scenarios.add_argument("--thinking", choices=["auto", "enabled", "disabled"], default="auto")
    model_scenarios.add_argument("--reasoning-effort", choices=["high", "max"], default="high")

    journal_parser = sub.add_parser("journal")
    journal_sub = journal_parser.add_subparsers(dest="journal_command", required=True)
    journal_sub.add_parser("tail")

    args = parser.parse_args(argv)
    journal = JournalStore(Path(args.journal), index_path=Path(args.index))

    if args.command == "run":
        result = _loop(journal, answer=f"respond: {args.text}", planner_mode=args.planner).run(args.text)
        print(json.dumps(result.__dict__, ensure_ascii=False, sort_keys=True))
        return 0

    if args.command == "agent":
        if _agent_uses_live_model(args) and os.environ.get("HOLO_V3_LIVE_MODEL") != "1":
            print(json.dumps({"status": "blocked", "reason": "live_model_not_enabled"}, sort_keys=True))
            return 1
        runtime = _agent_runtime(
            journal,
            live_model=_agent_uses_live_model(args),
            model=args.model,
            profile=args.profile,
            thinking=_thinking_override(args.thinking),
            reasoning_effort=args.reasoning_effort,
            memory_store=_memory_store(args, create_default=False),
        )
        payload = runtime.run(
            args.goal,
            mode=args.mode,
            planner_mode=args.planner,
            evaluator_mode=args.evaluator,
            synthesizer_mode=args.synthesizer,
            semantic_mode=args.semantic_intake,
            citations_required=True if args.citations_required else None,
        )
        print(json.dumps(payload.to_dict(), ensure_ascii=False, sort_keys=True))
        return 0

    if args.command == "answer":
        runtime = _agent_runtime(journal, live_model=False, memory_store=_memory_store(args, create_default=False))
        payload = runtime.run(
            args.goal,
            mode="retrieval" if args.citations_required else "auto",
            citations_required=True if args.citations_required else None,
        )
        print(json.dumps(payload.to_dict(), ensure_ascii=False, sort_keys=True))
        return 0

    if args.command == "chat":
        if _agent_uses_live_model(args) and os.environ.get("HOLO_V3_LIVE_MODEL") != "1":
            print(json.dumps({"status": "blocked", "reason": "live_model_not_enabled"}, sort_keys=True))
            return 1
        runtime = _chat_runtime(
            journal,
            memory_store=_memory_store(args, create_default=False),
            live_model=_agent_uses_live_model(args),
            model=args.model,
            profile=args.profile,
            thinking=_thinking_override(args.thinking),
            reasoning_effort=args.reasoning_effort,
            planner_mode=args.planner,
            evaluator_mode=args.evaluator,
            synthesizer_mode=args.synthesizer,
            semantic_mode=args.semantic_intake,
        )
        if args.once is not None:
            payload = runtime.receive(args.once, thread_id=args.thread)
            print(json.dumps(payload.to_dict(), ensure_ascii=False, sort_keys=True))
            return 0 if payload.status not in {"failed", "blocked"} else 1
        for line in sys.stdin:
            text = line.strip()
            if not text:
                continue
            payload = runtime.receive(text, thread_id=args.thread)
            print(json.dumps(payload.to_dict(), ensure_ascii=False, sort_keys=True))
            sys.stdout.flush()
        return 0

    if args.command == "chat-status":
        runtime = _chat_runtime(journal, memory_store=_memory_store(args, create_default=False))
        print(json.dumps(runtime.build_thread_state(args.thread_id).to_dict(), ensure_ascii=False, sort_keys=True))
        return 0

    if args.command == "chat-summary":
        runtime = _chat_runtime(journal, memory_store=_memory_store(args, create_default=False))
        summary = runtime.summarize_thread(args.thread_id)
        print(json.dumps(summary.to_dict(), ensure_ascii=False, sort_keys=True))
        return 0

    if args.command == "memory":
        payload = _memory_command(args, journal)
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        return 0 if payload.get("status") != "failed" else 1

    if args.command == "resident":
        if (
            getattr(args, "resident_command", None) in {"run", "run-once"}
            and _agent_uses_live_model(args)
            and os.environ.get("HOLO_V3_LIVE_MODEL") != "1"
        ):
            print(json.dumps({"status": "blocked", "reason": "live_model_not_enabled"}, sort_keys=True))
            return 1
        payload = _resident_command(args, journal)
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        return 0 if payload.get("status") not in {"failed", "blocked"} else 1

    if args.command == "inspect-run":
        renderer = TraceRenderer(journal)
        print(
            json.dumps(
                {
                    "task_id": args.task_id,
                    "trace": renderer.render_task(args.task_id, verbose=True),
                    "evidence": renderer.render_evidence(args.task_id),
                    "artifacts": renderer.render_artifacts(args.task_id),
                    "retrieval_trace": renderer.render_retrieval_trace(args.task_id),
                    "memory_trace": renderer.render_memory_trace(args.task_id),
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 0

    if args.command == "inspect-workloop":
        print(json.dumps(_workloop_payload(journal, args.task_id), ensure_ascii=False, sort_keys=True))
        return 0

    if args.command == "final-answer":
        payload = _latest_record_payload(journal, args.task_id, "agent_final_answer")
        print(json.dumps(payload or {"status": "missing", "task_id": args.task_id}, ensure_ascii=False, sort_keys=True))
        return 0 if payload else 1

    if args.command == "failure-report":
        payload = _latest_record_payload(journal, args.task_id, "agent_failure_report")
        print(json.dumps(payload or {"status": "missing", "task_id": args.task_id}, ensure_ascii=False, sort_keys=True))
        return 0 if payload else 1

    if args.command == "retrieve":
        payload = _run_retrieve(journal, query=args.query, body=args.body, synthesizer_mode=args.synthesizer)
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        return 0

    if args.command == "resume":
        result = _loop(journal, answer=f"resumed: {args.text}").resume(args.task_id, user_input=args.text)
        print(json.dumps(result.__dict__, ensure_ascii=False, sort_keys=True))
        return 0

    if args.command == "trace":
        print(TraceRenderer(journal).render_task(args.task_id, verbose=args.verbose))
        return 0

    if args.command == "evidence":
        print(TraceRenderer(journal).render_evidence(args.task_id))
        return 0

    if args.command == "artifacts":
        print(TraceRenderer(journal).render_artifacts(args.task_id))
        return 0

    if args.command == "retrieval-trace":
        print(TraceRenderer(journal).render_retrieval_trace(args.task_id))
        return 0

    if args.command == "memory-trace":
        print(TraceRenderer(journal).render_memory_trace(args.task_id))
        return 0
    if args.command == "resident-trace":
        print(TraceRenderer(journal).render_resident_trace())
        return 0

    if args.command == "context":
        task_id = args.legacy_task_id or getattr(args, "task_id", None)
        if task_id is None:
            parser.error("context requires a task_id or a context subcommand")
        state = _active_task(journal, task_id)
        pack = ContextPackCompiler(
            permission_state={"mode": "read_write"},
            durable_memory_store=_memory_store(args, create_default=False),
        ).compile(
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

    if args.command == "providers":
        print(json.dumps(_providers_payload(), ensure_ascii=False, sort_keys=True))
        return 0

    if args.command == "provider-smoke":
        if not args.fake:
            parser.error("provider-smoke currently requires --fake")
        outcome = _fake_processor_fabric(journal).run_json(
            task_type="planner.propose",
            run_id="run-provider-smoke",
            context_id="ctx-provider-smoke",
            prompt="Return a valid planner action.",
            schema=PLANNER_SCHEMA,
            task_id=None,
        )
        print(json.dumps(_outcome_payload(outcome), ensure_ascii=False, sort_keys=True))
        return 0 if outcome.result.status == "ok" else 1

    if args.command == "model-smoke":
        if os.environ.get("HOLO_V3_LIVE_MODEL") != "1":
            print(json.dumps({"status": "blocked", "reason": "live_model_not_enabled"}, sort_keys=True))
            return 1
        fabric = _live_processor_fabric(
            args.provider,
            journal,
            model=args.model,
            profile="fast",
            thinking=_thinking_override(args.thinking),
            reasoning_effort=args.reasoning_effort,
        )
        outcome = fabric.run_json(
            task_type="planner.propose",
            run_id="run-model-smoke",
            context_id="ctx-model-smoke",
            prompt=_model_smoke_prompt("model smoke ok"),
            schema=PLANNER_SCHEMA,
            task_id=None,
            provider=args.provider,
            model=args.model,
        )
        print(json.dumps(_outcome_payload(outcome), ensure_ascii=False, sort_keys=True))
        return 0 if outcome.result.status == "ok" else 1

    if args.command == "model-scenarios":
        if os.environ.get("HOLO_V3_LIVE_MODEL") != "1":
            print(json.dumps({"status": "blocked", "reason": "live_model_not_enabled"}, sort_keys=True))
            return 1
        fabric = _live_processor_fabric(
            args.provider,
            journal,
            model=args.model,
            profile=args.profile,
            thinking=_thinking_override(args.thinking),
            reasoning_effort=args.reasoning_effort,
        )
        results = run_semantic_scenarios(
            fabric,
            task_id="task-model-scenarios",
            run_id="run-model-scenarios",
            context_id="ctx-model-scenarios",
            provider=args.provider,
            model=args.model,
        )
        payload = scenario_report_payload(results)
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        return 0 if payload["status"] == "ok" else 1

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


def _loop(journal: JournalStore, *, answer: str, planner_mode: str = "fake") -> LoopControllerV3:
    registry = ToolRegistry.with_fake_workspace_tools(files={"README.md": "Holo local kernel"})
    planner = FakePlanner.respond_once(answer)
    if planner_mode == "model":
        planner = ModelPlanner(
            fabric=_fake_processor_fabric(journal, answer=answer),
            allowed_tool_names={manifest.name for manifest in registry.manifests()},
        )
    return LoopControllerV3(
        journal=journal,
        context_compiler=ContextCompiler(),
        planner=planner,
        policy_gate=PolicyGate(permission="read_write"),
        tool_registry=registry,
        evaluator=FakeEvaluator.final_answer(answer),
    )


def _agent_runtime(
    journal: JournalStore,
    *,
    live_model: bool,
    model: str | None = None,
    profile: str = "balanced",
    thinking: str | None = None,
    reasoning_effort: str = "high",
    memory_store: MemoryStore | None = None,
) -> AgentRuntime:
    fabric = (
        _live_processor_fabric(
            "deepseek",
            journal,
            model=model,
            profile=profile,
            thinking=thinking,
            reasoning_effort=reasoning_effort,
        )
        if live_model
        else None
    )
    return AgentRuntime(
        journal=journal,
        processor_fabric=fabric,
        workspace_root=Path.cwd(),
        memory_store=memory_store,
    )


def _chat_runtime(
    journal: JournalStore,
    *,
    memory_store: MemoryStore | None = None,
    live_model: bool = False,
    model: str | None = None,
    profile: str = "balanced",
    thinking: str | None = None,
    reasoning_effort: str = "high",
    planner_mode: str = "fake",
    evaluator_mode: str = "fake",
    synthesizer_mode: str = "fake",
    semantic_mode: str = "fake",
) -> ChatRuntime:
    return ChatRuntime(
        journal=journal,
        agent_runtime=_agent_runtime(
            journal,
            live_model=live_model,
            model=model,
            profile=profile,
            thinking=thinking,
            reasoning_effort=reasoning_effort,
            memory_store=memory_store,
        ),
        memory_store=memory_store,
        planner_mode=planner_mode,
        evaluator_mode=evaluator_mode,
        synthesizer_mode=synthesizer_mode,
        semantic_mode=semantic_mode,
    )


def _memory_store(args, *, create_default: bool) -> MemoryStore | None:
    memory_log = getattr(args, "memory_log", None)
    memory_index = getattr(args, "memory_index", None)
    if memory_log is None and not create_default:
        return None
    log_path = Path(memory_log or "kernel_v3/.holo-v3-memory.jsonl")
    index_path = Path(memory_index) if memory_index is not None else log_path.with_suffix(".sqlite")
    return MemoryStore(log_path, index_path=index_path)


def _memory_command(args, journal: JournalStore) -> dict[str, object]:
    store = _memory_store(args, create_default=True)
    if store is None:
        return {"status": "failed", "reason": "memory_store_not_configured"}
    command = args.memory_command
    if command == "list":
        scope = {"thread_id": args.thread} if args.thread else None
        result = store.recall(query=args.query, scope=scope)
        return {"status": "ok", "result": result.to_dict()}
    if command == "proposals":
        proposals = [proposal.to_dict() for proposal in store.proposals()]
        if args.thread:
            proposals = [proposal for proposal in proposals if proposal.get("source_thread_id") == args.thread]
        return {"status": "ok", "proposals": proposals}
    pipeline = MemoryPipeline(store=store, journal=journal)
    if command == "propose":
        result = pipeline.propose_from_semantic_intake(
            analyze_goal(args.text),
            task_id="task-cli-memory",
            run_id="run-cli-memory",
            thread_id=args.thread,
            source_record_ref=None,
        )
        return {"status": "ok", "result": result.to_dict()}
    if command == "approve":
        result = pipeline.approve_proposal(args.proposal_id, approved_by="user")
        return {"status": "ok", "result": result.to_dict()}
    if command == "reject":
        result = pipeline.reject_proposal(args.proposal_id, reason=args.reason)
        return {"status": "ok", "result": result.to_dict()}
    if command == "delete":
        tombstone = store.delete(args.memory_id, reason=args.reason, deleted_by="user")
        return {"status": "ok", "tombstone": tombstone.to_dict()}
    if command == "export":
        return {"status": "ok", "export": store.export_item(args.memory_id)}
    if command == "migrate-semantic":
        from kernel_v3.memory.migration import migrate_semantic_intake_records

        report = migrate_semantic_intake_records(journal=journal, store=store, limit=args.limit)
        return {"status": "ok", "migration": report.to_dict()}
    return {"status": "failed", "reason": f"unknown_memory_command:{command}"}


def _resident_queue(args) -> ResidentQueue:
    db_path = Path(getattr(args, "resident_db", None) or "kernel_v3/.holo-v3-resident.sqlite")
    return ResidentQueue(db_path)


def _resident_command(args, journal: JournalStore) -> dict[str, object]:
    queue = _resident_queue(args)
    command = args.resident_command
    if command == "enqueue":
        message = queue.enqueue(thread_id=args.thread, text=args.text, source="cli", message_id=args.message_id)
        journal.append(
            task_id=None,
            run_id="resident-cli",
            step_id=None,
            kind="resident_inbox_enqueued",
            data=message.to_dict(),
            state_delta={"resident_inbox_status": message.status, "resident_message_id": message.message_id},
        )
        return {"status": "ok", "message": message.to_dict()}
    if command == "inbox":
        return {"status": "ok", "messages": [message.to_dict() for message in queue.inbox_messages()]}
    if command == "outbox":
        return {"status": "ok", "messages": [message.to_dict() for message in queue.outbox_messages()]}
    if command == "status":
        return {"status": "ok", "queue": queue.status().to_dict()}
    if command == "requeue":
        message = queue.requeue(
            args.message_id,
            reason=args.reason,
            reset_attempts=not args.keep_attempts,
        )
        if message is None:
            return {"status": "failed", "reason": "inbox_not_requeueable_or_missing", "message_id": args.message_id}
        journal.append(
            task_id=None,
            run_id="resident-cli",
            step_id=None,
            kind="resident_inbox_requeued",
            data=message.to_dict(),
            state_delta={"resident_inbox_status": message.status, "resident_message_id": message.message_id},
        )
        return {"status": "ok", "message": message.to_dict()}
    if command in {"run-once", "run"}:
        memory_store = _memory_store(args, create_default=False)
        runtime = ResidentRuntime(
            queue=queue,
            chat_runtime=_chat_runtime(
                journal,
                memory_store=memory_store,
                live_model=_agent_uses_live_model(args),
                model=getattr(args, "model", None),
                profile=getattr(args, "profile", "balanced"),
                thinking=_thinking_override(getattr(args, "thinking", "auto")),
                reasoning_effort=getattr(args, "reasoning_effort", "high"),
                planner_mode=getattr(args, "planner", "fake"),
                evaluator_mode=getattr(args, "evaluator", "fake"),
                synthesizer_mode=getattr(args, "synthesizer", "fake"),
                semantic_mode=getattr(args, "semantic_intake", "fake"),
            ),
            worker_id=args.worker_id,
            max_attempts=args.max_attempts,
            retry_backoff_ms=args.retry_backoff_ms,
            journal=journal,
        )
        if command == "run":
            return runtime.run_loop(max_iterations=args.max_iterations).to_dict()
        return runtime.run_once().to_dict()
    if command == "ack":
        outbox = queue.mark_outbox_status(args.outbox_id, status=args.status)
        if outbox is None:
            return {"status": "failed", "reason": "outbox_not_found", "outbox_id": args.outbox_id}
        journal.append(
            task_id=outbox.task_id,
            run_id="resident-cli",
            step_id=None,
            kind="resident_outbox_ack",
            data=outbox.to_dict(),
            state_delta={"resident_outbox_status": outbox.status, "resident_outbox_id": outbox.outbox_id},
        )
        return {"status": "ok", "outbox": outbox.to_dict()}
    return {"status": "failed", "reason": f"unknown_resident_command:{command}"}


def _agent_uses_live_model(args) -> bool:
    return any(
        value == "model"
        for value in (
            getattr(args, "planner", "fake"),
            getattr(args, "evaluator", "fake"),
            getattr(args, "synthesizer", "fake"),
            getattr(args, "semantic_intake", "fake"),
        )
    )


def _workloop_payload(journal: JournalStore, task_id: str) -> dict[str, object]:
    return {
        "task_id": task_id,
        "progress_assessments": [
            record.data for record in journal.records(task_id=task_id, kind="progress_assessment")
        ],
        "repetition_signals": [
            record.data for record in journal.records(task_id=task_id, kind="repetition_signal")
        ],
        "evidence_sufficiency": [
            record.data for record in journal.records(task_id=task_id, kind="evidence_sufficiency")
        ],
        "termination_decisions": [
            record.data for record in journal.records(task_id=task_id, kind="termination_decision")
        ],
        "final_answer": _latest_record_payload(journal, task_id, "agent_final_answer"),
        "failure_report": _latest_record_payload(journal, task_id, "agent_failure_report"),
    }


def _latest_record_payload(journal: JournalStore, task_id: str, kind: str):
    records = journal.records(task_id=task_id, kind=kind)
    return records[-1].data if records else None


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


def _fake_processor_fabric(journal: JournalStore, *, answer: str = "processor smoke ok") -> ProcessorFabric:
    return ProcessorFabric(
        providers={
            "fake_json": FakeJsonProvider(
                {
                    "planner.propose": {
                        "action_id": "act-model-respond",
                        "kind": "respond",
                        "name": None,
                        "description": "respond through host",
                        "payload": {"text": answer},
                        "score": 1.0,
                        "reasons": ["fake processor smoke"],
                        "side_effect_class": "none",
                    },
                    "synthesizer.answer": {
                        "answer": answer,
                        "citation_refs": ["cite-evidence-span-doc-goal-cli-1-1"],
                        "confidence": 1.0,
                        "limitations": [],
                        "used_evidence": ["evidence-span-doc-goal-cli-1-1"],
                    },
                }
            )
        },
        router=ProcessorRouter(default_provider="fake_json", default_model="fake-json"),
        journal=journal,
    )


def _live_processor_fabric(
    provider: str,
    journal: JournalStore,
    *,
    model: str | None = None,
    profile: str = "balanced",
    thinking: str | None = None,
    reasoning_effort: str = "high",
) -> ProcessorFabric:
    providers = {
        "deepseek": DeepSeekProvider(enabled=True, model=model),
        "openai_compatible": OpenAICompatibleProvider(enabled=True, model=model or "local-model"),
    }
    if provider == "deepseek":
        router = deepseek_v4_router(profile=profile, thinking=thinking, reasoning_effort=reasoning_effort)
    else:
        router = ProcessorRouter(default_provider=provider, default_model=providers[provider].model)
    return ProcessorFabric(
        providers=providers,
        router=router,
        journal=journal,
    )


def _run_retrieve(
    journal: JournalStore,
    *,
    query: str,
    body: str | None,
    synthesizer_mode: str,
) -> dict[str, object]:
    from kernel_v3.context import ArtifactStore

    artifacts = ArtifactStore.in_memory()
    source = SearchSource(
        source_id="src-cli-1",
        uri="https://example.test/holo-v3-cli",
        title="Holo v3 CLI evidence",
        snippet=query,
        provider="fake",
    )
    retrieval_body = body or f"{query} evidence from a fake bounded retrieval provider."
    operator = RetrievalOperator(
        search_provider=FakeSearchProvider({query: [source]}),
        fetch_provider=FakeFetchProvider({source.uri: retrieval_body}),
    )
    report = operator.run(
        SearchGoal(goal_id="goal-cli", query=query, max_spans_per_document=1),
        journal=journal,
        artifact_store=artifacts,
        task_id="task-cli-retrieve",
        run_id="run-cli-retrieve",
        step_id_prefix="cli-retrieve",
    )
    payload: dict[str, object] = {"report": report.to_dict()}
    if synthesizer_mode == "model":
        evidence = [
            record.data
            for record in journal.records(task_id="task-cli-retrieve", kind="retrieval_evidence")
            if isinstance(record.data, dict)
        ]
        citations = [
            record.data
            for record in journal.records(task_id="task-cli-retrieve", kind="retrieval_citation")
            if isinstance(record.data, dict)
        ]
        from kernel_v3.retrieval.contracts import CitationItem, EvidenceItem

        answer = Synthesizer(fabric=_fake_processor_fabric(journal, answer=report.preview)).synthesize(
            task_id="task-cli-retrieve",
            run_id="run-cli-retrieve",
            context_id="ctx-cli-retrieve",
            report=report,
            evidence=[EvidenceItem.from_dict(item) for item in evidence],
            citations=[CitationItem.from_dict(item) for item in citations],
        )
        payload["synthesis"] = answer.to_dict()
    return payload


def _providers_payload() -> list[dict[str, object]]:
    return [
        {"name": "fake_json", "live": False, "enabled_by_default": True},
        {"name": "fake_malformed_json", "live": False, "enabled_by_default": False},
        {"name": "fake_timeout", "live": False, "enabled_by_default": False},
        {
            "name": "deepseek",
            "live": True,
            "enabled_by_default": False,
            "env_gated_by": "HOLO_V3_LIVE_MODEL",
            "default_model": DeepSeekProvider().model,
            "profiles": {
                "fast": {
                    "planner.propose": "deepseek-v4-flash",
                    "evaluator.assess": "deepseek-v4-flash",
                    "synthesizer.answer": "deepseek-v4-flash",
                },
                "balanced": {
                    "planner.propose": "deepseek-v4-flash",
                    "evaluator.assess": "deepseek-v4-pro",
                    "synthesizer.answer": "deepseek-v4-pro",
                },
                "quality": {
                    "planner.propose": "deepseek-v4-pro",
                    "evaluator.assess": "deepseek-v4-pro",
                    "synthesizer.answer": "deepseek-v4-pro",
                },
            },
            "thinking": {"default": "auto", "choices": ["auto", "enabled", "disabled"]},
            "reasoning_effort": {"default": "high", "choices": ["high", "max"]},
        },
        {
            "name": "openai_compatible",
            "live": True,
            "enabled_by_default": False,
            "env_gated_by": "HOLO_V3_LIVE_MODEL",
        },
    ]


def _thinking_override(value: str) -> str | None:
    return None if value == "auto" else value


def _model_smoke_prompt(text: str) -> str:
    return json.dumps(
        {
            "contract": PLANNER_PROMPT_CONTRACT,
            "task": "Return exactly one JSON object matching planner.propose.",
            "required_action": {
                "action_id": "act-model-smoke",
                "kind": "respond",
                "name": None,
                "description": "respond through host",
                "payload": {"text": text},
                "score": 1.0,
                "reasons": ["live provider smoke"],
                "side_effect_class": "none",
            },
        },
        ensure_ascii=False,
        sort_keys=True,
    )


def _outcome_payload(outcome) -> dict[str, object]:
    return {
        "status": outcome.result.status,
        "provider": outcome.provider,
        "model": outcome.model,
        "task_type": outcome.task_type,
        "duration_ms": outcome.duration_ms,
        "parsed": outcome.parsed,
        "error": outcome.result.error,
    }


if __name__ == "__main__":
    raise SystemExit(main())
