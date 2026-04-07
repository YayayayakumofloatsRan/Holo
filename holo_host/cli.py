from __future__ import annotations

import argparse
import json

from .config import load_config
from .daemon import build_daemon
from .models import ProcessorTaskRequest
from .reply_api import HoloReplyService, run_reply_api
from .store import QueueStore


def _mind_context(daemon, *, thread_key: str | None, chat_name: str | None, channel: str, sender: str | None) -> dict:
    return {
        "channel": channel,
        "thread_key": thread_key or "",
        "chat_name": chat_name or "",
        "sender": sender or "",
        "recall_trigger_mode": daemon.config.memory.recall_trigger_mode,
        "mind_budget": {
            "fast_history_messages": daemon.config.memory.fast_history_messages,
            "recall_history_messages": daemon.config.memory.recall_history_messages,
            "fast_episodic_k": daemon.config.memory.fast_episodic_k,
            "recall_episodic_k": daemon.config.memory.recall_episodic_k,
            "fast_consciousness_k": daemon.config.memory.fast_consciousness_k,
            "recall_consciousness_k": daemon.config.memory.recall_consciousness_k,
        },
    }


def command_init_db(config_path: str | None) -> int:
    config = load_config(config_path=config_path)
    store = QueueStore(config.runtime.db_path)
    store.initialize()
    print(json.dumps({"db_path": str(config.runtime.db_path), "status": "ok"}, ensure_ascii=False, indent=2))
    return 0


def command_cycle(config_path: str | None) -> int:
    daemon = build_daemon(config_path)
    result = daemon.run_cycle()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def command_daemon(config_path: str | None) -> int:
    daemon = build_daemon(config_path)
    daemon.run_forever()
    return 0


def command_jobs(config_path: str | None, limit: int) -> int:
    config = load_config(config_path=config_path)
    store = QueueStore(config.runtime.db_path)
    store.initialize()
    print(json.dumps(store.list_jobs(limit=limit), ensure_ascii=False, indent=2))
    return 0


def command_followups(config_path: str | None, limit: int) -> int:
    config = load_config(config_path=config_path)
    store = QueueStore(config.runtime.db_path)
    store.initialize()
    created = store.schedule_due_followups(config.autonomy.proactive_after_hours, limit=limit)
    print(json.dumps({"created_job_ids": created}, ensure_ascii=False, indent=2))
    return 0


def command_promote_memory(config_path: str | None) -> int:
    daemon = build_daemon(config_path)
    print(json.dumps(daemon.memory.promote_ready_candidates(limit=daemon.config.memory.promote_batch_size), ensure_ascii=False, indent=2))
    return 0


def command_backfill_archive(config_path: str | None, db_path: str | None, *, dry_run: bool) -> int:
    daemon = build_daemon(config_path)
    print(json.dumps(daemon.memory.backfill_archive(db_path=db_path, dry_run=dry_run), ensure_ascii=False, indent=2))
    return 0


def command_backfill_mind_graph(config_path: str | None, *, dry_run: bool) -> int:
    daemon = build_daemon(config_path)
    print(json.dumps(daemon.memory.backfill_mind_graph(dry_run=dry_run), ensure_ascii=False, indent=2))
    return 0


def command_dream_cycle(config_path: str | None, sample_size: int, *, seed: str | None, dry_run: bool) -> int:
    daemon = build_daemon(config_path)
    print(
        json.dumps(
            daemon.memory.run_dream_cycle(sample_size=sample_size, seed=seed, dry_run=dry_run),
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def command_think_cycle(config_path: str | None, sample_size: int, *, seed: str | None, dry_run: bool) -> int:
    daemon = build_daemon(config_path)
    print(
        json.dumps(
            daemon.memory.run_think_cycle(sample_size=sample_size, seed=seed, dry_run=dry_run),
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def command_reflect_cycle(config_path: str | None, window_hours: float, *, dry_run: bool) -> int:
    daemon = build_daemon(config_path)
    print(
        json.dumps(
            daemon.memory.run_reflect_cycle(window_hours=window_hours, dry_run=dry_run),
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def command_initiative_cycle(config_path: str | None, *, dry_run: bool) -> int:
    daemon = build_daemon(config_path)
    print(json.dumps(daemon.memory.run_initiative_cycle(dry_run=dry_run), ensure_ascii=False, indent=2))
    return 0


def command_show_callbacks(config_path: str | None, limit: int) -> int:
    daemon = build_daemon(config_path)
    print(json.dumps(daemon.memory.list_callback_candidates(limit=limit), ensure_ascii=False, indent=2))
    return 0


def command_show_thoughts(config_path: str | None, limit: int) -> int:
    daemon = build_daemon(config_path)
    print(json.dumps(daemon.memory.list_thoughts(limit=limit), ensure_ascii=False, indent=2))
    return 0


def command_show_initiatives(config_path: str | None, limit: int) -> int:
    daemon = build_daemon(config_path)
    print(json.dumps(daemon.memory.list_initiative_candidates(limit=limit), ensure_ascii=False, indent=2))
    return 0


def command_inspect_mind(
    config_path: str | None,
    *,
    query: str,
    thread_key: str | None,
    chat_name: str | None,
    channel: str,
    sender: str | None,
) -> int:
    daemon = build_daemon(config_path)
    packet = daemon.memory.inspect_mind(query, context=_mind_context(daemon, thread_key=thread_key, chat_name=chat_name, channel=channel, sender=sender))
    print(json.dumps(packet, ensure_ascii=False, indent=2))
    return 0


def command_inspect_graph(
    config_path: str | None,
    *,
    thread_key: str | None,
    chat_name: str | None,
    channel: str,
    limit: int,
) -> int:
    daemon = build_daemon(config_path)
    print(
        json.dumps(
            daemon.memory.inspect_graph(thread_key=thread_key, chat_name=chat_name, channel=channel, limit=limit),
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def command_trace_recall(
    config_path: str | None,
    *,
    query: str,
    thread_key: str | None,
    chat_name: str | None,
    channel: str,
    limit: int,
) -> int:
    daemon = build_daemon(config_path)
    print(
        json.dumps(
            daemon.memory.trace_recall(query, thread_key=thread_key, chat_name=chat_name, channel=channel, limit=limit),
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def command_reply_probe(
    config_path: str | None,
    *,
    query: str,
    thread_key: str | None,
    chat_name: str | None,
    channel: str,
    sender: str | None,
) -> int:
    config = load_config(config_path=config_path)
    service = HoloReplyService(config)
    print(
        json.dumps(
            service.reply_probe(
                {
                    "chat_name": chat_name or thread_key or "",
                    "thread_key": thread_key or "",
                    "channel": channel,
                    "sender": sender or chat_name or thread_key or "",
                    "text": query,
                }
            ),
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def command_show_stream_status(config_path: str | None) -> int:
    daemon = build_daemon(config_path)
    print(json.dumps(daemon.memory.stream_status(), ensure_ascii=False, indent=2))
    return 0


def command_show_processor_mesh(config_path: str | None) -> int:
    daemon = build_daemon(config_path)
    print(json.dumps({"tasks": daemon.runner.supported_tasks()}, ensure_ascii=False, indent=2))
    return 0


def command_run_processor_task(
    config_path: str | None,
    *,
    task_type: str,
    prompt: str,
    session_id: str | None,
    model: str | None,
    reasoning_effort: str | None,
    json_output: bool,
) -> int:
    daemon = build_daemon(config_path)
    result = daemon.runner.run_task(
        ProcessorTaskRequest(
            task_type=task_type,
            prompt=prompt,
            session_id=str(session_id or ""),
            model_override=str(model or ""),
            reasoning_effort_override=str(reasoning_effort or ""),
            output_schema="json" if json_output else "plain_text",
        )
    )
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    return 0


def command_experiment_memory(
    config_path: str | None,
    *,
    thread_key: str | None,
    chat_name: str | None,
    channel: str,
    sender: str | None,
) -> int:
    daemon = build_daemon(config_path)
    context = _mind_context(daemon, thread_key=thread_key, chat_name=chat_name, channel=channel, sender=sender)
    scenarios = [
        ("casual_ping", "在吗"),
        ("identity_check", "你还是你吗"),
        ("explicit_recall", "你还记得重新上线前吗"),
    ]
    results: list[dict] = []
    for name, query in scenarios:
        packet = daemon.memory.inspect_mind(query, context=context)
        results.append(
            {
                "name": name,
                "query": query,
                "tier": packet.get("tier", "fast"),
                "recall_reason": packet.get("recall_reason", "none"),
                "selected_memory_ids": list(packet.get("selected_memory_ids", [])),
                "relationship_summary": packet.get("relationship_summary", ""),
                "thread_summary": packet.get("thread_summary", ""),
                "episodic_lines": list(packet.get("episodic_lines", [])),
                "consciousness_lines": list(packet.get("consciousness_lines", [])),
            }
        )
    print(json.dumps({"channel": channel, "thread_key": thread_key or "", "chat_name": chat_name or "", "scenarios": results}, ensure_ascii=False, indent=2))
    return 0


def command_snapshot_memory(config_path: str | None, path: str | None, label: str | None, query: str | None) -> int:
    daemon = build_daemon(config_path)
    print(json.dumps(daemon.memory.export_snapshot(path=path, label=label, query=query), ensure_ascii=False, indent=2))
    return 0


def command_restore_memory(
    config_path: str | None,
    path: str,
    *,
    mode: str,
    dry_run: bool,
    restore_persona_files: bool,
) -> int:
    daemon = build_daemon(config_path)
    print(
        json.dumps(
            daemon.memory.import_snapshot(
                path,
                mode=mode,
                dry_run=dry_run,
                restore_persona=restore_persona_files,
            ),
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def command_revive_packet(config_path: str | None, path: str | None, query: str | None, as_json: bool) -> int:
    daemon = build_daemon(config_path)
    packet = daemon.memory.revive_packet(query=query, snapshot_path=path)
    if as_json:
        print(json.dumps(packet, ensure_ascii=False, indent=2))
    else:
        print(packet["text"])
    return 0


def command_serve_api(config_path: str | None, host: str | None, port: int | None) -> int:
    run_reply_api(config_path=config_path, host=host, port=port)
    return 0


def command_ingest_artifact(
    config_path: str | None,
    path: str,
    *,
    note: str | None,
    tags: list[str],
    source: str,
    dry_run: bool,
) -> int:
    daemon = build_daemon(config_path)
    print(
        json.dumps(
            daemon.memory.ingest_artifact(
                path,
                note=note,
                source=source,
                tags=tags,
                dry_run=dry_run,
            ),
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def command_refresh_wechat_history(
    config_path: str | None,
    *,
    chat_name: str,
    thread_key: str | None,
    query: str | None,
    force: bool,
    limit: int | None,
    page_turns: int | None,
    include_visible: bool,
    include_captures: bool,
) -> int:
    config = load_config(config_path=config_path)
    service = HoloReplyService(config)
    print(
        json.dumps(
            service.refresh_wechat_history(
                {
                    "chat_name": chat_name,
                    "thread_key": thread_key or "",
                    "channel": "wechat",
                    "query": query or "",
                    "force": force,
                    "limit": limit,
                    "page_turns": page_turns,
                    "include_visible": include_visible,
                    "include_captures": include_captures,
                }
            ),
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Holo WSL host daemon")
    parser.add_argument("--config", default=None, help="Path to .holo_host.toml")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("init-db", help="Initialize the runtime SQLite store")
    subparsers.add_parser("cycle", help="Run one ingest/process/promote cycle")
    subparsers.add_parser("daemon", help="Run the host daemon forever")
    jobs_parser = subparsers.add_parser("jobs", help="Show recent queue jobs")
    jobs_parser.add_argument("--limit", type=int, default=50)
    followups_parser = subparsers.add_parser("schedule-followups", help="Schedule due proactive followups")
    followups_parser.add_argument("--limit", type=int, default=10)
    subparsers.add_parser("promote-memory", help="Promote ready candidate memories")
    backfill_parser = subparsers.add_parser("backfill-archive", help="Backfill archive turns from holo_host.sqlite3")
    backfill_parser.add_argument("--db-path", default=None)
    backfill_parser.add_argument("--dry-run", action="store_true")
    backfill_graph_parser = subparsers.add_parser("backfill-mind-graph", help="Rebuild the SQLite-backed Mind Graph from archive and stores")
    backfill_graph_parser.add_argument("--dry-run", action="store_true")
    dream_parser = subparsers.add_parser("dream-cycle", help="Replay archive turns into candidate memory and callback candidates")
    dream_parser.add_argument("--sample-size", type=int, default=6)
    dream_parser.add_argument("--seed", default=None)
    dream_parser.add_argument("--dry-run", action="store_true")
    think_parser = subparsers.add_parser("think-cycle", help="Run one internal thought cycle")
    think_parser.add_argument("--sample-size", type=int, default=4)
    think_parser.add_argument("--seed", default=None)
    think_parser.add_argument("--dry-run", action="store_true")
    reflect_parser = subparsers.add_parser("reflect-cycle", help="Run one reflection cycle")
    reflect_parser.add_argument("--window-hours", type=float, default=12.0)
    reflect_parser.add_argument("--dry-run", action="store_true")
    initiative_cycle_parser = subparsers.add_parser("initiative-cycle", help="Refresh initiative candidates")
    initiative_cycle_parser.add_argument("--dry-run", action="store_true")
    callbacks_parser = subparsers.add_parser("show-callbacks", help="Inspect callback candidates")
    callbacks_parser.add_argument("--limit", type=int, default=20)
    thoughts_parser = subparsers.add_parser("show-thoughts", help="Inspect recent thought-stream rows")
    thoughts_parser.add_argument("--limit", type=int, default=20)
    initiatives_parser = subparsers.add_parser("show-initiatives", help="Inspect initiative candidates")
    initiatives_parser.add_argument("--limit", type=int, default=20)
    inspect_parser = subparsers.add_parser("inspect-mind", help="Inspect the structured mind packet for a thread/query")
    inspect_parser.add_argument("--query", required=True)
    inspect_parser.add_argument("--thread-key", default=None)
    inspect_parser.add_argument("--chat-name", default=None)
    inspect_parser.add_argument("--channel", default="wechat")
    inspect_parser.add_argument("--sender", default=None)
    inspect_graph_parser = subparsers.add_parser("inspect-graph", help="Inspect the materialized Mind Graph for one thread or contact")
    inspect_graph_parser.add_argument("--thread-key", default=None)
    inspect_graph_parser.add_argument("--chat-name", default=None)
    inspect_graph_parser.add_argument("--channel", default="wechat")
    inspect_graph_parser.add_argument("--limit", type=int, default=12)
    trace_parser = subparsers.add_parser("trace-recall", help="Trace recall activation through the materialized Mind Graph")
    trace_parser.add_argument("--query", required=True)
    trace_parser.add_argument("--thread-key", default=None)
    trace_parser.add_argument("--chat-name", default=None)
    trace_parser.add_argument("--channel", default="wechat")
    trace_parser.add_argument("--limit", type=int, default=8)
    reply_probe_parser = subparsers.add_parser("reply-probe", help="Compare graph-led and legacy reply drafts without sending anything")
    reply_probe_parser.add_argument("--query", required=True)
    reply_probe_parser.add_argument("--thread-key", default=None)
    reply_probe_parser.add_argument("--chat-name", default=None)
    reply_probe_parser.add_argument("--channel", default="wechat")
    reply_probe_parser.add_argument("--sender", default=None)
    experiment_parser = subparsers.add_parser("experiment-memory", help="Run a fixed three-scenario mind-packet experiment")
    experiment_parser.add_argument("--thread-key", default=None)
    experiment_parser.add_argument("--chat-name", default=None)
    experiment_parser.add_argument("--channel", default="wechat")
    experiment_parser.add_argument("--sender", default=None)
    snapshot_parser = subparsers.add_parser("snapshot-memory", help="Write a portable Holo self snapshot")
    snapshot_parser.add_argument("--path", default=None)
    snapshot_parser.add_argument("--label", default=None)
    snapshot_parser.add_argument("--query", default=None)
    restore_parser = subparsers.add_parser("restore-memory", help="Restore or merge a saved Holo self snapshot")
    restore_parser.add_argument("--path", required=True)
    restore_parser.add_argument("--mode", choices=("merge", "replace"), default="merge")
    restore_parser.add_argument("--dry-run", action="store_true")
    restore_parser.add_argument("--restore-persona-files", action="store_true")
    revive_parser = subparsers.add_parser("revive-packet", help="Print a portable revive packet from live memory or a snapshot")
    revive_parser.add_argument("--path", default=None)
    revive_parser.add_argument("--query", default=None)
    revive_parser.add_argument("--json", action="store_true")
    artifact_parser = subparsers.add_parser("ingest-artifact", help="Read a local text/document/image artifact into Holo memory")
    artifact_parser.add_argument("--path", required=True)
    artifact_parser.add_argument("--note", default=None)
    artifact_parser.add_argument("--tags", nargs="*", default=[])
    artifact_parser.add_argument("--source", default="holo_host.cli.artifact")
    artifact_parser.add_argument("--dry-run", action="store_true")
    refresh_wechat_parser = subparsers.add_parser("refresh-wechat-history", help="Actively pull one WeChat thread history through the Windows helper and ingest it into memory")
    refresh_wechat_parser.add_argument("--chat-name", required=True)
    refresh_wechat_parser.add_argument("--thread-key", default=None)
    refresh_wechat_parser.add_argument("--query", default=None)
    refresh_wechat_parser.add_argument("--limit", type=int, default=None)
    refresh_wechat_parser.add_argument("--page-turns", type=int, default=None)
    refresh_wechat_parser.add_argument("--force", action="store_true")
    refresh_wechat_parser.add_argument("--no-visible", action="store_true")
    refresh_wechat_parser.add_argument("--with-captures", action="store_true")
    subparsers.add_parser("show-stream-status", help="Show background Mind OS stream status and recent runs")
    subparsers.add_parser("show-processor-mesh", help="Show supported processor task types and permissions")
    processor_task_parser = subparsers.add_parser("processor-task", help="Run one explicit processor-mesh task through Codex")
    processor_task_parser.add_argument("--task-type", required=True)
    processor_task_parser.add_argument("--prompt", required=True)
    processor_task_parser.add_argument("--session-id", default=None)
    processor_task_parser.add_argument("--model", default=None)
    processor_task_parser.add_argument("--reasoning-effort", default=None)
    processor_task_parser.add_argument("--json", action="store_true")
    serve_parser = subparsers.add_parser("serve-api", help="Run a local Codex-direct HTTP reply service for external helpers")
    serve_parser.add_argument("--host", default=None)
    serve_parser.add_argument("--port", type=int, default=None)

    args = parser.parse_args(argv)
    if args.command == "init-db":
        return command_init_db(args.config)
    if args.command == "cycle":
        return command_cycle(args.config)
    if args.command == "daemon":
        return command_daemon(args.config)
    if args.command == "jobs":
        return command_jobs(args.config, args.limit)
    if args.command == "schedule-followups":
        return command_followups(args.config, args.limit)
    if args.command == "promote-memory":
        return command_promote_memory(args.config)
    if args.command == "backfill-archive":
        return command_backfill_archive(args.config, args.db_path, dry_run=args.dry_run)
    if args.command == "backfill-mind-graph":
        return command_backfill_mind_graph(args.config, dry_run=args.dry_run)
    if args.command == "dream-cycle":
        return command_dream_cycle(args.config, args.sample_size, seed=args.seed, dry_run=args.dry_run)
    if args.command == "think-cycle":
        return command_think_cycle(args.config, args.sample_size, seed=args.seed, dry_run=args.dry_run)
    if args.command == "reflect-cycle":
        return command_reflect_cycle(args.config, args.window_hours, dry_run=args.dry_run)
    if args.command == "initiative-cycle":
        return command_initiative_cycle(args.config, dry_run=args.dry_run)
    if args.command == "show-callbacks":
        return command_show_callbacks(args.config, args.limit)
    if args.command == "show-thoughts":
        return command_show_thoughts(args.config, args.limit)
    if args.command == "show-initiatives":
        return command_show_initiatives(args.config, args.limit)
    if args.command == "inspect-mind":
        return command_inspect_mind(
            args.config,
            query=args.query,
            thread_key=args.thread_key,
            chat_name=args.chat_name,
            channel=args.channel,
            sender=args.sender,
        )
    if args.command == "inspect-graph":
        return command_inspect_graph(
            args.config,
            thread_key=args.thread_key,
            chat_name=args.chat_name,
            channel=args.channel,
            limit=args.limit,
        )
    if args.command == "trace-recall":
        return command_trace_recall(
            args.config,
            query=args.query,
            thread_key=args.thread_key,
            chat_name=args.chat_name,
            channel=args.channel,
            limit=args.limit,
        )
    if args.command == "reply-probe":
        return command_reply_probe(
            args.config,
            query=args.query,
            thread_key=args.thread_key,
            chat_name=args.chat_name,
            channel=args.channel,
            sender=args.sender,
        )
    if args.command == "experiment-memory":
        return command_experiment_memory(
            args.config,
            thread_key=args.thread_key,
            chat_name=args.chat_name,
            channel=args.channel,
            sender=args.sender,
        )
    if args.command == "snapshot-memory":
        return command_snapshot_memory(args.config, args.path, args.label, args.query)
    if args.command == "restore-memory":
        return command_restore_memory(
            args.config,
            args.path,
            mode=args.mode,
            dry_run=args.dry_run,
            restore_persona_files=args.restore_persona_files,
        )
    if args.command == "revive-packet":
        return command_revive_packet(args.config, args.path, args.query, args.json)
    if args.command == "ingest-artifact":
        return command_ingest_artifact(
            args.config,
            args.path,
            note=args.note,
            tags=args.tags,
            source=args.source,
            dry_run=args.dry_run,
        )
    if args.command == "refresh-wechat-history":
        return command_refresh_wechat_history(
            args.config,
            chat_name=args.chat_name,
            thread_key=args.thread_key,
            query=args.query,
            force=args.force,
            limit=args.limit,
            page_turns=args.page_turns,
            include_visible=not args.no_visible,
            include_captures=args.with_captures,
        )
    if args.command == "show-stream-status":
        return command_show_stream_status(args.config)
    if args.command == "show-processor-mesh":
        return command_show_processor_mesh(args.config)
    if args.command == "processor-task":
        return command_run_processor_task(
            args.config,
            task_type=args.task_type,
            prompt=args.prompt,
            session_id=args.session_id,
            model=args.model,
            reasoning_effort=args.reasoning_effort,
            json_output=args.json,
        )
    if args.command == "serve-api":
        return command_serve_api(args.config, args.host, args.port)
    parser.print_help()
    return 1
