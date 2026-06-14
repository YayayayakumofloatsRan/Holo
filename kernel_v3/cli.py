from __future__ import annotations

import argparse
import html
import inspect
import json
import os
import sys
import urllib.parse
from dataclasses import replace
from pathlib import Path
from typing import Callable

from kernel_v3.agent import AgentRuntime
from kernel_v3.agent.contracts import SemanticIntake
from kernel_v3.agent.execution_profile import (
    EXECUTION_PROFILE_IDS,
    ExecutionProfile,
    execution_profile,
    execution_profile_runtime_metadata,
    profile_mission_enabled,
    profile_processor_mode,
)
from kernel_v3.behavior_graph import BehaviorGraphBuilder, build_benchmark_result_graph_from_path, render_behavior_graph_dot
from kernel_v3.bench import (
    PUBLIC_FINANCE_BENCHMARK_SPECS,
    FinanceBenchmarkItem,
    FinanceBenchmarkResult,
    build_finance_benchmark_report_from_path,
    convert_public_finance_benchmark,
    fetch_public_finance_benchmark,
    finance_benchmark_run_id,
    load_finance_benchmark_items,
    render_finance_benchmark_report,
    run_finance_benchmark,
    run_finance_benchmark_parallel,
    run_general_capability_gauntlet,
    score_finance_prediction_file,
    write_general_capability_gauntlet_outputs,
    write_finance_dev_annotations_from_dataset,
    write_finance_benchmark_outputs,
)
from kernel_v3.capabilities import semantic_capability_catalog
from kernel_v3.chat import ChatRuntime
from kernel_v3.chat.console import (
    ChatConsoleOptions,
    chat_color_enabled,
    chat_output_mode,
    print_chat_turn_human,
    public_chat_result_payload,
    render_chat_result,
    render_status_notice,
    run_chat_console,
)
from kernel_v3.chat.thread_store import ThreadTranscriptStore
from kernel_v3.context import ArtifactStore, ContextCompiler, ContextPackCompiler, merge_context_budget
from kernel_v3.contracts import JsonObject, LedgerRecord, ProcessorRequest
from kernel_v3.interaction import DEFAULT_RESPONSE_LANGUAGE, normalize_response_language
from kernel_v3.journal import JournalStore
from kernel_v3.loop import LoopControllerV3
from kernel_v3.memory import MemoryPipeline, MemoryStore
from kernel_v3.mission import MissionRuntime
from kernel_v3.policy import PolicyGate
from kernel_v3.processors import (
    CHAT_ROUTE_PROMPT_CONTRACT,
    EVALUATOR_PROMPT_CONTRACT,
    EVALUATOR_SCHEMA,
    MISSION_ASSESS_PROMPT_CONTRACT,
    PLANNER_SCHEMA,
    PLANNER_PROMPT_CONTRACT,
    SEMANTIC_INTAKE_PROMPT_CONTRACT,
    SYNTHESIZER_PROMPT_CONTRACT,
    DeepSeekProvider,
    FakeJsonProvider,
    ModelPlanner,
    OpenAICompatibleProvider,
    ProcessorFabric,
    ProcessorRouter,
    Synthesizer,
    adapt_generation_parameters,
    deepseek_v4_router,
    run_semantic_scenarios,
    scenario_report_payload,
)
from kernel_v3.research import (
    FINANCE_FUNDAMENTALS_PROFILE_ID,
    RESEARCH_PROFILE_IDS,
    RESEARCH_DEPTHS,
    ResearchCorpusStore,
    research_depth_defaults,
    site_index_families,
    site_index_list,
    site_index_plan,
    site_index_seeds,
)
from kernel_v3.retrieval import (
    CorpusFetchProvider,
    CorpusSearchProvider,
    FetchResponse,
    LiveRetrievalConfig,
    RetrievalOperator,
    RoutingFetchProvider,
    SearchGoal,
    SearchSource,
    UnconfiguredFetchProvider,
    UnconfiguredSearchProvider,
    inspect_retrieval_providers,
    retrieval_behavior_benchmark,
)
from kernel_v3.retrieval.live_config import (
    DEFAULT_LIVE_CACHE_DIR,
    DEFAULT_LIVE_DOWNLOAD_BYTE_BUDGET,
    LIVE_ALLOW_ALL_HOSTS_ENV,
    LIVE_CACHE_DIR_ENV,
    LIVE_CRAWL_INCLUDE_SITEMAPS_ENV,
    LIVE_CRAWL_MAX_LINKS_PER_PAGE_ENV,
    LIVE_CRAWL_MAX_PAGES_ENV,
    LIVE_CRAWL_MAX_SITEMAP_URLS_ENV,
    LIVE_CRAWL_MAX_SOURCE_DIRECTORY_SEEDS_ENV,
    LIVE_CRAWL_SEED_URLS_ENV,
    LIVE_CRAWL_SOURCE_DIRECTORY_ENV,
    LIVE_FETCH_DISCOVERED_SEARCH_HOSTS_ENV,
    LIVE_FETCH_ALLOWED_HOSTS_ENV,
    LIVE_DOWNLOAD_BYTE_BUDGET_ENV,
    LIVE_MAX_BYTES_ENV,
    LIVE_RETRIEVAL_ENV,
    LIVE_SEARCH_ALLOWED_HOSTS_ENV,
    LIVE_SEARCH_ENDPOINT_ENV,
    LIVE_SEARCH_MAX_SOURCES_PER_PROVIDER_ENV,
    LIVE_SEARCH_STRATEGY_ENV,
    LIVE_SOURCE_DIRECTORY_ALLOWLIST_ENV,
    LIVE_TIMEOUT_SECONDS_ENV,
    LIVE_WEB_SEARCH_MAX_RESULTS_PER_ENGINE_ENV,
    LIVE_WEB_SEARCH_PROVIDERS_ENV,
)
from kernel_v3.workmethod.prompts import WORKMETHOD_FRAME_PROMPT_CONTRACT, WORKMETHOD_GAP_PROMPT_CONTRACT
from kernel_v3.resident import ResidentDoctor, ResidentQueue, ResidentRuntime, ResidentScheduler
from kernel_v3.resident.projection import resident_doctor_event, resident_inbox_event, resident_outbox_event
from kernel_v3.storage import (
    default_journal_index_path,
    default_journal_path,
    default_memory_index_path,
    default_memory_log_path,
    default_thread_root,
    safe_storage_id,
)
from kernel_v3.testing.fakes import FakeEvaluator, FakePlanner
from kernel_v3.tools import ToolRegistry
from kernel_v3.trace import TraceRenderer


DEFAULT_LIVE_NETWORK_FETCH_BUDGET = 512
DEFAULT_LIVE_RETRIEVAL_FETCH_BUDGET = 128
DEFAULT_RESEARCH_DEPTH = "deep"
DEFAULT_LIVE_CONTEXT_PROFILE = "provider"
DEFAULT_LIVE_WEB_SEARCH_PROVIDERS = "bing_html,duckduckgo_html"
DEFAULT_LIVE_SEARCH_STRATEGY = "aggregate"


def _add_live_retrieval_args(command_parser: argparse.ArgumentParser) -> None:
    command_parser.add_argument(
        "--live-retrieval",
        dest="live_retrieval",
        action="store_true",
        default=None,
        help="Enable live retrieval for this command. Network use still requires PolicyGate permission and host allowlists.",
    )
    command_parser.add_argument(
        "--no-live-retrieval",
        dest="live_retrieval",
        action="store_false",
        help="Disable live retrieval for this command, even when online chat/agent mode would enable bounded web discovery.",
    )
    command_parser.add_argument("--live-max-network-fetches", type=int, default=DEFAULT_LIVE_NETWORK_FETCH_BUDGET)
    command_parser.add_argument(
        "--live-allow-all-hosts",
        action="store_true",
        help="Explicitly bypass live retrieval host allowlists for this run. Use only for trusted smoke tests.",
    )
    command_parser.add_argument("--live-search-endpoint", default=None)
    command_parser.add_argument(
        "--live-web-search-provider",
        action="append",
        default=None,
        help="Enable a live HTML web search provider for this run. Repeat or comma-separate values such as duckduckgo_html,bing_html.",
    )
    command_parser.add_argument("--live-web-search-max-results-per-engine", type=int, default=None)
    command_parser.add_argument(
        "--live-fetch-discovered-search-hosts",
        dest="live_fetch_discovered_search_hosts",
        action="store_true",
        default=None,
        help="Allow live HTTP fetch of safe URLs returned by live_web_search, still bounded by policy and budgets.",
    )
    command_parser.add_argument(
        "--no-live-fetch-discovered-search-hosts",
        dest="live_fetch_discovered_search_hosts",
        action="store_false",
    )
    command_parser.add_argument("--live-search-allowed-host", action="append", default=None)
    command_parser.add_argument("--live-fetch-allowed-host", action="append", default=None)
    command_parser.add_argument("--live-crawl-seed-url", action="append", default=None)
    command_parser.add_argument("--live-crawl-source-directory", action="store_true")
    command_parser.add_argument("--live-source-directory-allowlist", action="store_true")
    command_parser.add_argument("--live-crawl-max-pages", type=int, default=None)
    command_parser.add_argument("--live-crawl-max-links-per-page", type=int, default=None)
    command_parser.add_argument("--live-crawl-max-sitemap-urls", type=int, default=None)
    command_parser.add_argument("--live-crawl-max-source-directory-seeds", type=int, default=None)
    command_parser.add_argument("--no-live-crawl-sitemaps", dest="live_crawl_include_sitemaps", action="store_false")
    command_parser.add_argument("--live-search-strategy", choices=["fallback", "aggregate", "adaptive"], default=None)
    command_parser.add_argument("--live-search-max-sources-per-provider", type=int, default=None)
    command_parser.add_argument("--live-timeout-seconds", type=int, default=None)
    command_parser.add_argument("--live-max-bytes", type=int, default=None)
    command_parser.add_argument(
        "--live-download-byte-budget",
        type=int,
        default=DEFAULT_LIVE_DOWNLOAD_BYTE_BUDGET,
        help="Total live HTTP download byte budget for this process/cache scope. Cache hits do not count.",
    )
    command_parser.add_argument(
        "--live-cache-dir",
        default=DEFAULT_LIVE_CACHE_DIR,
        help="Directory for live HTTP response cache shared across benchmark workers. Use an empty string to disable.",
    )


def _add_online_model_arg(command_parser: argparse.ArgumentParser) -> None:
    command_parser.add_argument(
        "--online",
        "--live-model",
        dest="online",
        action="store_true",
        help="Enable the model-backed semantic stack. Chat defaults to live unless --offline is passed.",
    )


def _add_response_language_arg(command_parser: argparse.ArgumentParser) -> None:
    command_parser.add_argument(
        "--response-language",
        default=None,
        help=f"Default language for user-visible model text when the user does not specify one. Default: {DEFAULT_RESPONSE_LANGUAGE}.",
    )


def _add_context_budget_args(command_parser: argparse.ArgumentParser, *, default_profile: str = "compact") -> None:
    command_parser.add_argument(
        "--context-profile",
        choices=["compact", "large", "huge", "provider"],
        default=default_profile,
        help="Host prompt/input budget profile. Live model runs default to provider-scale input budgets.",
    )
    command_parser.add_argument("--context-token-budget", type=int, default=None)
    command_parser.add_argument("--context-section-budget", type=int, default=None)
    command_parser.add_argument("--workspace-evidence-chars", type=int, default=None)
    command_parser.add_argument("--synthesis-evidence-preview-chars", type=int, default=None)


def _add_generation_args(command_parser: argparse.ArgumentParser) -> None:
    command_parser.add_argument(
        "--generation-mode",
        choices=["auto", "manual"],
        default="auto",
        help="auto lets the host adapt thinking/reasoning/temperature/timeout per processor call; manual preserves route/user settings.",
    )
    command_parser.add_argument(
        "--latency-target",
        choices=["fast", "balanced", "quality", "thorough"],
        default="balanced",
        help="Adaptive generation target used when --generation-mode auto.",
    )
    command_parser.add_argument(
        "--max-output-tokens",
        default="provider",
        help="Output token cap for live processor calls: provider/none disables max_tokens, auto uses route defaults, or pass an integer.",
    )
    command_parser.add_argument("--temperature", type=float, default=None)


def _add_agent_loop_args(command_parser: argparse.ArgumentParser) -> None:
    command_parser.add_argument("--max-agent-steps", type=int, default=None)
    command_parser.add_argument("--max-agent-tool-calls", type=int, default=None)
    command_parser.add_argument("--max-agent-artifact-bytes", type=int, default=None)


def main(argv: list[str] | None = None) -> int:
    argv = _normalize_argv(list(sys.argv[1:] if argv is None else argv))
    parser = argparse.ArgumentParser(prog="holo-v3")
    parser.add_argument("--journal", default=str(default_journal_path()))
    parser.add_argument("--index", default=str(default_journal_index_path()))
    parser.add_argument("--artifact-log", default=None)
    parser.add_argument("--corpus-log", default=None)
    parser.add_argument("--corpus-index", default=None)
    parser.add_argument("--memory-log", default=None)
    parser.add_argument("--memory-index", default=None)
    parser.add_argument("--thread-store-root", default=None)
    parser.add_argument("--resident-db", default=None)
    sub = parser.add_subparsers(dest="command", required=True)

    run_parser = sub.add_parser("run")
    run_parser.add_argument("--planner", choices=["fake", "model"], default="fake")
    run_parser.add_argument("text")

    agent_parser = sub.add_parser("agent")
    agent_parser.add_argument("goal")
    agent_parser.add_argument(
        "--mode",
        choices=["direct", "semantic", "retrieval", "workspace", "write", "system", "time", "auto"],
        default="auto",
    )
    agent_parser.add_argument("--planner", choices=["fake", "model"], default="fake")
    agent_parser.add_argument("--evaluator", choices=["fake", "model"], default="fake")
    agent_parser.add_argument("--synthesizer", choices=["fake", "model"], default="fake")
    agent_parser.add_argument("--semantic-intake", choices=["fake", "model"], default="fake")
    _add_online_model_arg(agent_parser)
    agent_parser.add_argument(
        "--offline",
        dest="online",
        action="store_false",
        help="Use fake/offline processors only for deterministic host diagnostics. Product agent runs default to live.",
    )
    agent_parser.set_defaults(online=True)
    agent_parser.add_argument("--model", default=None)
    agent_parser.add_argument("--profile", choices=["fast", "balanced", "quality"], default="balanced")
    agent_parser.add_argument("--thinking", choices=["auto", "enabled", "disabled"], default="auto")
    agent_parser.add_argument("--reasoning-effort", choices=["low", "medium", "high", "max"], default="high")
    _add_generation_args(agent_parser)
    _add_agent_loop_args(agent_parser)
    _add_context_budget_args(agent_parser, default_profile=DEFAULT_LIVE_CONTEXT_PROFILE)
    _add_response_language_arg(agent_parser)
    agent_parser.add_argument("--citations-required", action="store_true")
    agent_parser.add_argument("--research-profile", choices=RESEARCH_PROFILE_IDS, default=None)
    agent_parser.add_argument("--research-depth", choices=RESEARCH_DEPTHS, default=DEFAULT_RESEARCH_DEPTH)
    _add_live_retrieval_args(agent_parser)

    answer_parser = sub.add_parser("answer")
    answer_parser.add_argument("goal")
    _add_context_budget_args(answer_parser)
    _add_response_language_arg(answer_parser)
    answer_parser.add_argument("--citations-required", action="store_true")
    answer_parser.add_argument("--research-profile", choices=RESEARCH_PROFILE_IDS, default=None)
    answer_parser.add_argument("--research-depth", choices=RESEARCH_DEPTHS, default=DEFAULT_RESEARCH_DEPTH)

    chat_parser = sub.add_parser("chat")
    chat_parser.add_argument("--thread", default="default")
    chat_parser.add_argument("--once", default=None)
    chat_parser.add_argument(
        "--output",
        choices=["auto", "human", "json"],
        default="auto",
        help="Chat output format. auto keeps --once and pipes machine-readable, while terminal chat is human-readable.",
    )
    chat_parser.add_argument("--color", choices=["auto", "always", "never"], default="auto")
    chat_parser.add_argument("--no-color", action="store_true", help="Alias for --color never.")
    chat_parser.add_argument("--planner", choices=["fake", "model"], default="fake")
    chat_parser.add_argument("--evaluator", choices=["fake", "model"], default="fake")
    chat_parser.add_argument("--synthesizer", choices=["fake", "model"], default="fake")
    chat_parser.add_argument("--semantic-intake", choices=["fake", "model"], default="fake")
    chat_parser.add_argument("--turn-router", choices=["fake", "model"], default="fake")
    _add_online_model_arg(chat_parser)
    chat_parser.add_argument(
        "--offline",
        dest="online",
        action="store_false",
        help="Use fake/offline processors for deterministic local checks. The interactive default is live.",
    )
    chat_parser.set_defaults(online=True)
    chat_parser.add_argument("--model", default=None)
    chat_parser.add_argument("--profile", choices=["fast", "balanced", "quality"], default="balanced")
    chat_parser.add_argument("--thinking", choices=["auto", "enabled", "disabled"], default="auto")
    chat_parser.add_argument("--reasoning-effort", choices=["low", "medium", "high", "max"], default="high")
    _add_generation_args(chat_parser)
    _add_agent_loop_args(chat_parser)
    _add_context_budget_args(chat_parser, default_profile=DEFAULT_LIVE_CONTEXT_PROFILE)
    _add_response_language_arg(chat_parser)
    chat_parser.add_argument("--research-profile", choices=RESEARCH_PROFILE_IDS, default=None)
    chat_parser.add_argument("--research-depth", choices=RESEARCH_DEPTHS, default=DEFAULT_RESEARCH_DEPTH)
    _add_live_retrieval_args(chat_parser)

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
    memory_inspect = memory_sub.add_parser("inspect")
    memory_inspect.add_argument("--sample-limit", type=int, default=5)
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
    resident_parser.add_argument("--output", choices=["json", "human"], default="json")
    resident_sub = resident_parser.add_subparsers(dest="resident_command", required=True)
    resident_enqueue = resident_sub.add_parser("enqueue")
    resident_enqueue.add_argument("text")
    resident_enqueue.add_argument("--thread", default="default")
    resident_enqueue.add_argument("--priority", type=int, default=0)
    resident_enqueue.add_argument("--message-id", default=None)
    resident_run_once = resident_sub.add_parser("run-once")
    resident_run_once.add_argument("--worker-id", default="resident-worker-1")
    resident_run_once.add_argument("--max-attempts", type=int, default=3)
    resident_run_once.add_argument("--retry-backoff-ms", type=int, default=1000)
    resident_run_once.add_argument("--planner", choices=["fake", "model"], default="fake")
    resident_run_once.add_argument("--evaluator", choices=["fake", "model"], default="fake")
    resident_run_once.add_argument("--synthesizer", choices=["fake", "model"], default="fake")
    resident_run_once.add_argument("--semantic-intake", choices=["fake", "model"], default="fake")
    resident_run_once.add_argument("--turn-router", choices=["fake", "model"], default="fake")
    _add_online_model_arg(resident_run_once)
    resident_run_once.add_argument(
        "--offline",
        dest="online",
        action="store_false",
        help="Use fake/offline processors only for deterministic host diagnostics. Resident runs default to live.",
    )
    resident_run_once.set_defaults(online=True)
    resident_run_once.add_argument("--model", default=None)
    resident_run_once.add_argument("--profile", choices=["fast", "balanced", "quality"], default="balanced")
    resident_run_once.add_argument("--thinking", choices=["auto", "enabled", "disabled"], default="auto")
    resident_run_once.add_argument("--reasoning-effort", choices=["low", "medium", "high", "max"], default="high")
    _add_generation_args(resident_run_once)
    _add_context_budget_args(resident_run_once, default_profile=DEFAULT_LIVE_CONTEXT_PROFILE)
    _add_response_language_arg(resident_run_once)
    resident_run_once.add_argument("--research-profile", choices=RESEARCH_PROFILE_IDS, default=None)
    resident_run_once.add_argument("--research-depth", choices=RESEARCH_DEPTHS, default=DEFAULT_RESEARCH_DEPTH)
    _add_live_retrieval_args(resident_run_once)
    resident_run_once.add_argument("--tick-schedules", action="store_true")
    resident_run_once.add_argument("--schedule-tick-limit", type=int, default=20)
    resident_run = resident_sub.add_parser("run")
    resident_run.add_argument("--worker-id", default="resident-worker-1")
    resident_run.add_argument("--max-iterations", type=int, default=10)
    resident_run.add_argument("--max-duration-ms", type=int, default=None)
    resident_run.add_argument("--max-attempts", type=int, default=3)
    resident_run.add_argument("--retry-backoff-ms", type=int, default=1000)
    resident_run.add_argument("--planner", choices=["fake", "model"], default="fake")
    resident_run.add_argument("--evaluator", choices=["fake", "model"], default="fake")
    resident_run.add_argument("--synthesizer", choices=["fake", "model"], default="fake")
    resident_run.add_argument("--semantic-intake", choices=["fake", "model"], default="fake")
    resident_run.add_argument("--turn-router", choices=["fake", "model"], default="fake")
    _add_online_model_arg(resident_run)
    resident_run.add_argument(
        "--offline",
        dest="online",
        action="store_false",
        help="Use fake/offline processors only for deterministic host diagnostics. Resident runs default to live.",
    )
    resident_run.set_defaults(online=True)
    resident_run.add_argument("--model", default=None)
    resident_run.add_argument("--profile", choices=["fast", "balanced", "quality"], default="balanced")
    resident_run.add_argument("--thinking", choices=["auto", "enabled", "disabled"], default="auto")
    resident_run.add_argument("--reasoning-effort", choices=["low", "medium", "high", "max"], default="high")
    _add_generation_args(resident_run)
    _add_context_budget_args(resident_run, default_profile=DEFAULT_LIVE_CONTEXT_PROFILE)
    _add_response_language_arg(resident_run)
    resident_run.add_argument("--research-profile", choices=RESEARCH_PROFILE_IDS, default=None)
    resident_run.add_argument("--research-depth", choices=RESEARCH_DEPTHS, default=DEFAULT_RESEARCH_DEPTH)
    _add_live_retrieval_args(resident_run)
    resident_run.add_argument("--tick-schedules", action="store_true")
    resident_run.add_argument("--schedule-tick-limit", type=int, default=20)
    resident_inspect = resident_sub.add_parser("inspect")
    resident_inspect.add_argument("--sample-limit", type=int, default=5)
    resident_doctor = resident_sub.add_parser("doctor")
    resident_doctor.add_argument("--sample-limit", type=int, default=5)
    resident_doctor.add_argument("--research-profile", choices=RESEARCH_PROFILE_IDS, default=None)
    _add_live_retrieval_args(resident_doctor)
    resident_sub.add_parser("status")
    resident_sub.add_parser("inbox")
    resident_sub.add_parser("outbox")
    resident_requeue = resident_sub.add_parser("requeue")
    resident_requeue.add_argument("message_id")
    resident_requeue.add_argument("--reason", default="manual_requeue")
    resident_requeue.add_argument("--keep-attempts", action="store_true")
    resident_cancel = resident_sub.add_parser("cancel")
    resident_cancel.add_argument("message_id")
    resident_cancel.add_argument("--reason", default="manual_cancel")
    resident_ack = resident_sub.add_parser("ack")
    resident_ack.add_argument("outbox_id")
    resident_ack.add_argument("--status", default="acknowledged")
    resident_retry_outbox = resident_sub.add_parser("retry-outbox")
    resident_retry_outbox.add_argument("outbox_id")
    resident_retry_outbox.add_argument("--reason", default="manual_retry")
    resident_schedule_add = resident_sub.add_parser("schedule-add")
    resident_schedule_add.add_argument("text")
    resident_schedule_add.add_argument("--thread", default="default")
    resident_schedule_add.add_argument("--schedule-id", default=None)
    resident_schedule_add.add_argument("--due-at-ms", type=int, default=None)
    resident_schedule_add.add_argument("--due-in-ms", type=int, default=0)
    resident_schedule_add.add_argument("--interval-ms", type=int, default=None)
    resident_schedule_add.add_argument("--max-runs", type=int, default=1)
    resident_schedule_add.add_argument("--priority", type=int, default=0)
    resident_schedule_add.add_argument("--unbounded", action="store_true")
    resident_schedule_tick = resident_sub.add_parser("schedule-tick")
    resident_schedule_tick.add_argument("--limit", type=int, default=20)
    resident_schedule_list = resident_sub.add_parser("schedule-list")
    resident_schedule_list.add_argument("--include-inactive", action="store_true")
    resident_schedule_disable = resident_sub.add_parser("schedule-disable")
    resident_schedule_disable.add_argument("schedule_id")
    resident_schedule_disable.add_argument("--reason", default="manual_disable")

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
    retrieve_parser.add_argument("--uri", default="inline://holo-v3-cli")
    retrieve_parser.add_argument("--title", default="Holo v3 CLI inline evidence")
    retrieve_parser.add_argument("--profile", choices=RESEARCH_PROFILE_IDS, default=None)
    retrieve_parser.add_argument("--max-queries", type=int, default=None)
    retrieve_parser.add_argument("--max-sources", type=int, default=5)
    retrieve_parser.add_argument("--max-fetches", type=int, default=3)
    retrieve_parser.add_argument("--max-spans-per-document", type=int, default=1)
    retrieve_parser.add_argument("--index-corpus", action="store_true")
    retrieve_parser.add_argument("--from-corpus", action="store_true")
    _add_live_retrieval_args(retrieve_parser)

    retrieval_providers_parser = sub.add_parser("retrieval-providers")
    retrieval_providers_parser.add_argument("--mode", choices=["default", "corpus", "live-http"], default="default")
    retrieval_providers_parser.add_argument("--profile", choices=RESEARCH_PROFILE_IDS, default=None)
    _add_live_retrieval_args(retrieval_providers_parser)

    corpus_parser = sub.add_parser("corpus")
    corpus_sub = corpus_parser.add_subparsers(dest="corpus_command", required=True)
    corpus_list = corpus_sub.add_parser("list")
    corpus_list.add_argument("--profile", choices=RESEARCH_PROFILE_IDS, default=None)
    corpus_list.add_argument("--limit", type=int, default=20)
    corpus_search = corpus_sub.add_parser("search")
    corpus_search.add_argument("query")
    corpus_search.add_argument("--profile", choices=RESEARCH_PROFILE_IDS, default=None)
    corpus_search.add_argument("--limit", type=int, default=20)
    corpus_inspect = corpus_sub.add_parser("inspect")
    corpus_inspect.add_argument("document_id")
    corpus_inspect_store = corpus_sub.add_parser("inspect-store")
    corpus_inspect_store.add_argument("--sample-limit", type=int, default=5)
    corpus_inspect_store.add_argument("--profile", choices=RESEARCH_PROFILE_IDS, default=None)
    corpus_sub.add_parser("status")
    corpus_audit = corpus_sub.add_parser("audit")
    corpus_audit.add_argument("--limit", type=int, default=20)
    corpus_sub.add_parser("index")

    sources_parser = sub.add_parser("sources")
    sources_sub = sources_parser.add_subparsers(dest="sources_command", required=True)
    sources_list = sources_sub.add_parser("list")
    sources_list.add_argument(
        "--profile",
        choices=RESEARCH_PROFILE_IDS,
        default=FINANCE_FUNDAMENTALS_PROFILE_ID,
    )
    sources_list.add_argument("--authority", choices=["primary", "secondary", "weak"], default=None)
    sources_list.add_argument("--family", default=None)
    sources_list.add_argument("--source-id", default=None)
    sources_list.add_argument("--limit", type=int, default=100)
    sources_seeds = sources_sub.add_parser("seeds")
    sources_seeds.add_argument(
        "--profile",
        choices=RESEARCH_PROFILE_IDS,
        default=FINANCE_FUNDAMENTALS_PROFILE_ID,
    )
    sources_seeds.add_argument("--authority", choices=["primary", "secondary", "weak"], default=None)
    sources_seeds.add_argument("--family", default=None)
    sources_seeds.add_argument("--source-id", default=None)
    sources_seeds.add_argument("--limit", type=int, default=100)
    sources_plan = sources_sub.add_parser("plan")
    sources_plan.add_argument("query")
    sources_plan.add_argument(
        "--profile",
        choices=RESEARCH_PROFILE_IDS,
        default=FINANCE_FUNDAMENTALS_PROFILE_ID,
    )
    sources_plan.add_argument("--authority", choices=["primary", "secondary", "weak"], default=None)
    sources_plan.add_argument("--family", default=None)
    sources_plan.add_argument("--limit", type=int, default=12)
    sources_families = sources_sub.add_parser("families")
    sources_families.add_argument(
        "--profile",
        choices=RESEARCH_PROFILE_IDS,
        default=FINANCE_FUNDAMENTALS_PROFILE_ID,
    )

    trace_parser = sub.add_parser("trace")
    trace_parser.add_argument("task_id")
    trace_parser.add_argument("--verbose", action="store_true")

    evidence_parser = sub.add_parser("evidence")
    evidence_parser.add_argument("task_id")

    artifacts_parser = sub.add_parser("artifacts")
    artifacts_parser.add_argument("task_id")

    retrieval_trace_parser = sub.add_parser("retrieval-trace")
    retrieval_trace_parser.add_argument("task_id")
    retrieval_benchmark_parser = sub.add_parser("retrieval-benchmark")
    retrieval_benchmark_parser.add_argument("task_id")
    behavior_graph_parser = sub.add_parser("behavior-graph")
    behavior_graph_parser.add_argument("task_id")
    behavior_graph_parser.add_argument("--format", choices=["json", "dot"], default="json")
    behavior_graph_parser.add_argument("--output", default=None)
    behavior_graph_parser.add_argument("--max-nodes", type=int, default=800)

    workflow_view = sub.add_parser("workflow-view")
    workflow_view.add_argument("--task-id", default=None, help="Render a specific task id.")
    workflow_view.add_argument("--thread-id", default=None, help="Render the latest task for a specific thread id.")
    workflow_view.add_argument("--thread-prefix", default=None, help="Render the latest task whose thread id starts with this prefix.")
    workflow_view.add_argument("--format", choices=["html", "json"], default="html")
    workflow_view.add_argument("--output", default=None, help="Output file path. HTML is written to stdout when omitted.")
    workflow_view.add_argument("--limit-events", type=int, default=240)

    bench_parser = sub.add_parser("bench")
    bench_sub = bench_parser.add_subparsers(dest="bench_command", required=True)
    general_bench = bench_sub.add_parser("general")
    general_bench.add_argument("--output", default=".state/kernel_v3/bench/general/latest.json")
    general_bench.add_argument("--summary-output", default=".state/kernel_v3/bench/general/latest.summary.json")
    general_bench.add_argument("--jsonl-output", default=".state/kernel_v3/bench/general/latest.jsonl")
    general_bench.add_argument("--thread-prefix", default="general-gauntlet")
    general_bench.add_argument(
        "--live",
        action="store_true",
        help="Run cases through the live chat runtime instead of the contract-only host capability gauntlet.",
    )
    general_bench.add_argument("--planner", choices=["fake", "model"], default="model")
    general_bench.add_argument("--evaluator", choices=["fake", "model"], default="model")
    general_bench.add_argument("--synthesizer", choices=["fake", "model"], default="model")
    general_bench.add_argument("--semantic-intake", choices=["fake", "model"], default="model")
    general_bench.add_argument("--turn-router", choices=["fake", "model"], default="model")
    _add_online_model_arg(general_bench)
    general_bench.add_argument("--model", default=None)
    general_bench.add_argument("--profile", choices=["fast", "balanced", "quality"], default="balanced")
    general_bench.add_argument("--thinking", choices=["auto", "enabled", "disabled"], default="auto")
    general_bench.add_argument("--reasoning-effort", choices=["low", "medium", "high", "max"], default="medium")
    _add_generation_args(general_bench)
    _add_agent_loop_args(general_bench)
    _add_context_budget_args(general_bench, default_profile=DEFAULT_LIVE_CONTEXT_PROFILE)
    _add_response_language_arg(general_bench)
    general_bench.add_argument("--research-profile", choices=RESEARCH_PROFILE_IDS, default=None)
    general_bench.add_argument("--research-depth", choices=RESEARCH_DEPTHS, default=DEFAULT_RESEARCH_DEPTH)
    _add_live_retrieval_args(general_bench)
    finance_fetch = bench_sub.add_parser("finance-fetch")
    finance_fetch.add_argument(
        "--benchmark",
        required=True,
        choices=sorted(PUBLIC_FINANCE_BENCHMARK_SPECS),
        help="Public finance benchmark to download from a known direct URL or --url override.",
    )
    finance_fetch.add_argument("--output", required=True, help="Raw local output path.")
    finance_fetch.add_argument("--split", default=None, help="Optional benchmark split, such as finqa dev/test/train.")
    finance_fetch.add_argument("--url", default=None, help="Optional explicit source URL or file:// mirror.")
    finance_fetch.add_argument("--timeout", type=float, default=60.0)
    finance_fetch.add_argument("--max-bytes", type=int, default=32_000_000)
    finance_fetch.add_argument(
        "--mode",
        default=None,
        help="Optional import mode when --normalized-output is also provided.",
    )
    finance_fetch.add_argument("--normalized-output", default=None, help="Optional normalized Kernel v3 benchmark JSONL.")
    finance_fetch.add_argument("--manifest-output", default=None, help="Optional manifest for normalized import.")
    finance_fetch.add_argument("--annotation-output", default=None, help="Optional post-run dev annotation sidecar.")
    finance_fetch.add_argument("--limit", type=int, default=None)
    finance_fetch.add_argument("--offset", type=int, default=0)
    finance_import = bench_sub.add_parser("finance-import")
    finance_import.add_argument(
        "--benchmark",
        required=True,
        choices=sorted(PUBLIC_FINANCE_BENCHMARK_SPECS),
        help="Public finance benchmark format to normalize into Kernel v3 benchmark JSONL.",
    )
    finance_import.add_argument("--input", required=True, help="Local CSV/JSON/JSONL export from the public benchmark.")
    finance_import.add_argument("--output", required=True, help="Normalized Kernel v3 benchmark JSONL.")
    finance_import.add_argument(
        "--mode",
        default=None,
        help=(
            "Optional import mode. FinanceBench supports oracle_evidence, doc_retrieval, and question_only; "
            "FinQA/SECQUE/FinanceQA support oracle_context and question_only."
        ),
    )
    finance_import.add_argument(
        "--manifest-output",
        default=None,
        help="Optional provenance manifest recording source URL and prompt/gold handling policy.",
    )
    finance_import.add_argument(
        "--annotation-output",
        default=None,
        help="Optional post-run dev annotation JSONL for --dev-gold scoring; gold/reference fields stay out of prompts.",
    )
    finance_import.add_argument("--limit", type=int, default=None)
    finance_import.add_argument("--offset", type=int, default=0)
    finance_graph = bench_sub.add_parser("finance-graph")
    finance_graph.add_argument("--results", required=True, help="Finance benchmark result JSONL/JSON produced by bench finance.")
    finance_graph.add_argument("--benchmark-id", default="finance")
    finance_graph.add_argument("--format", choices=["json", "dot"], default="json")
    finance_graph.add_argument("--output", default=None)
    finance_graph.add_argument("--max-items", type=int, default=200)
    finance_report = bench_sub.add_parser("finance-report")
    finance_report.add_argument("--results", required=True, help="Finance benchmark result JSONL/JSON produced by bench finance.")
    finance_report.add_argument("--benchmark-id", default="finance")
    finance_report.add_argument("--title", default=None)
    finance_report.add_argument("--format", choices=["markdown", "html", "json"], default="markdown")
    finance_report.add_argument("--output", default=None)
    finance_report.add_argument("--max-weak-items", type=int, default=20)
    finance_progress = bench_sub.add_parser("finance-progress")
    finance_progress.add_argument("--task-id", default=None, help="Inspect a specific task id.")
    finance_progress.add_argument("--thread-id", default=None, help="Inspect the latest task for a specific thread id.")
    finance_progress.add_argument(
        "--thread-prefix",
        default=None,
        help="Inspect the latest task whose thread id starts with this prefix.",
    )
    finance_progress.add_argument(
        "--format",
        choices=["text", "json"],
        default="text",
        help="Render a human workflow snapshot or raw JSON.",
    )
    finance_progress.add_argument("--limit-events", type=int, default=24)
    finance_bench = bench_sub.add_parser("finance")
    finance_bench.add_argument("--dataset", required=True)
    finance_bench.add_argument("--predictions", default=None)
    finance_bench.add_argument("--output", default=".state/kernel_v3/bench/finance/latest.jsonl")
    finance_bench.add_argument("--summary-output", default=".state/kernel_v3/bench/finance/latest.summary.json")
    finance_bench.add_argument(
        "--dev-gold",
        default=None,
        help="Optional JSON/JSONL dev annotation file used only for post-run scoring; never included in prompts.",
    )
    finance_bench.add_argument("--limit", type=int, default=None)
    finance_bench.add_argument("--offset", type=int, default=0)
    finance_bench.add_argument("--thread-prefix", default="finance-bench")
    finance_bench.add_argument(
        "--execution-profile",
        choices=EXECUTION_PROFILE_IDS,
        default="finance-fact-fast",
        help="Execution lane for benchmark runs. Fast lanes bypass resident mission overhead; long-mission preserves full supervision.",
    )
    finance_bench.add_argument(
        "--mission",
        choices=["auto", "on", "off"],
        default="auto",
        help="Override MissionRuntime wrapping for benchmark runs. auto follows --execution-profile.",
    )
    finance_bench.add_argument(
        "--parallel",
        type=int,
        default=1,
        help="Run live benchmark questions concurrently. Each worker uses an isolated journal/state directory.",
    )
    finance_bench.add_argument(
        "--worker-state-root",
        default=None,
        help="Root directory for per-question worker state. Defaults to a fresh directory next to --output.",
    )
    finance_bench.add_argument(
        "--question-prefix",
        default="",
        help="Optional instruction prepended to each benchmark question. Gold answers are never included.",
    )
    finance_bench.add_argument("--planner", choices=["fake", "model"], default="model")
    finance_bench.add_argument("--evaluator", choices=["fake", "model"], default="model")
    finance_bench.add_argument("--synthesizer", choices=["fake", "model"], default="model")
    finance_bench.add_argument("--semantic-intake", choices=["fake", "model"], default="model")
    finance_bench.add_argument("--turn-router", choices=["fake", "model"], default="model")
    _add_online_model_arg(finance_bench)
    finance_bench.add_argument(
        "--offline",
        dest="online",
        action="store_false",
        help="Score existing predictions or run deterministic diagnostics without live processors. Live runs are the benchmark default.",
    )
    finance_bench.set_defaults(online=True)
    finance_bench.add_argument("--model", default=None)
    finance_bench.add_argument("--profile", choices=["fast", "balanced", "quality"], default="balanced")
    finance_bench.add_argument("--thinking", choices=["auto", "enabled", "disabled"], default="auto")
    finance_bench.add_argument("--reasoning-effort", choices=["low", "medium", "high", "max"], default="high")
    _add_generation_args(finance_bench)
    _add_agent_loop_args(finance_bench)
    _add_context_budget_args(finance_bench, default_profile=DEFAULT_LIVE_CONTEXT_PROFILE)
    _add_response_language_arg(finance_bench)
    finance_bench.add_argument(
        "--research-profile",
        choices=RESEARCH_PROFILE_IDS,
        default=FINANCE_FUNDAMENTALS_PROFILE_ID,
    )
    finance_bench.add_argument("--research-depth", choices=RESEARCH_DEPTHS, default=DEFAULT_RESEARCH_DEPTH)
    _add_live_retrieval_args(finance_bench)

    memory_trace_parser = sub.add_parser("memory-trace")
    memory_trace_parser.add_argument("task_id")
    resident_trace_parser = sub.add_parser("resident-trace")
    resident_trace_parser.add_argument("--limit", type=int, default=200)

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
    model_smoke.add_argument("--reasoning-effort", choices=["low", "medium", "high", "max"], default="high")
    _add_generation_args(model_smoke)

    model_scenarios = sub.add_parser("model-scenarios")
    model_scenarios.add_argument("--provider", choices=["deepseek", "openai_compatible"], required=True)
    model_scenarios.add_argument("--model", default=None)
    model_scenarios.add_argument("--profile", choices=["fast", "balanced", "quality"], default="balanced")
    model_scenarios.add_argument("--thinking", choices=["auto", "enabled", "disabled"], default="auto")
    model_scenarios.add_argument("--reasoning-effort", choices=["low", "medium", "high", "max"], default="high")
    _add_generation_args(model_scenarios)

    model_packet = sub.add_parser("model-packet")
    model_packet.add_argument("--provider", choices=["deepseek", "openai_compatible"], default="deepseek")
    model_packet.add_argument(
        "--task-type",
        choices=[
            "chat.route",
            "semantic.intake",
            "planner.propose",
            "task.compile",
            "retrieval.workbench",
            "finance.numeric_judge",
            "evaluator.assess",
            "synthesizer.answer",
            "mission.assess",
            "workmethod.frame",
            "workmethod.gap",
        ],
        default="planner.propose",
    )
    model_packet.add_argument("--goal", default="你能做什么？你是谁")
    model_packet.add_argument("--model", default=None)
    model_packet.add_argument("--profile", choices=["fast", "balanced", "quality"], default="balanced")
    model_packet.add_argument("--thinking", choices=["auto", "enabled", "disabled"], default="auto")
    model_packet.add_argument("--reasoning-effort", choices=["low", "medium", "high", "max"], default="high")
    model_packet.add_argument("--timeout-seconds", type=int, default=None)
    model_packet.add_argument("--max-tokens", type=int, default=None)
    _add_generation_args(model_packet)
    model_packet.add_argument("--show-prompt", action="store_true")

    journal_parser = sub.add_parser("journal")
    journal_sub = journal_parser.add_subparsers(dest="journal_command", required=True)
    journal_sub.add_parser("tail")

    args = parser.parse_args(argv)
    if args.command == "workflow-view":
        payload = _workflow_view_command_from_path(args)
        rendered = json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) if args.format == "json" else _render_workflow_view_html(payload)
        if args.output:
            path = Path(args.output)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(rendered, encoding="utf-8")
            print(str(path))
        else:
            print(rendered)
        return 0 if payload.get("status") not in {"failed", "blocked", "error"} else 1
    if args.command == "bench" and getattr(args, "bench_command", None) == "finance-progress":
        payload = _finance_progress_command_from_path(args)
        raw_output = _render_finance_progress(payload) if getattr(args, "format", "text") == "text" else None
        if isinstance(raw_output, str):
            print(raw_output)
        else:
            print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        return 0 if payload.get("status") not in {"failed", "blocked", "error"} else 1
    journal_index_path = None if args.command == "bench" and getattr(args, "bench_command", None) == "finance-progress" else Path(args.index)
    journal = JournalStore(Path(args.journal), index_path=journal_index_path)

    if args.command == "run":
        result = _loop(journal, answer=f"respond: {args.text}", planner_mode=args.planner).run(args.text)
        print(json.dumps(result.__dict__, ensure_ascii=False, sort_keys=True))
        return 0

    if args.command == "agent":
        live_block = _chat_live_model_block(args)
        if live_block is not None:
            print(json.dumps(live_block, sort_keys=True))
            return 1
        live_retrieval = _live_retrieval_config_for_args(args)
        if isinstance(live_retrieval, dict):
            print(json.dumps(live_retrieval, ensure_ascii=False, sort_keys=True))
            return 1
        artifact_store = _runtime_artifact_store(args)
        research_corpus_store = _runtime_corpus_store(args)
        runtime = _mission_runtime(
            _agent_runtime(
                journal,
                live_model=_agent_uses_live_model(args),
                model=args.model,
                profile=args.profile,
                thinking=_thinking_override(args.thinking),
                reasoning_effort=args.reasoning_effort,
                max_output_tokens=args.max_output_tokens,
                temperature=args.temperature,
                generation_mode=args.generation_mode,
                latency_target=args.latency_target,
                response_language=_response_language_for_args(args),
                artifact_store=artifact_store,
                memory_store=_memory_store(args, create_default=True),
                research_corpus_store=research_corpus_store,
                retrieval_operator=_build_live_retrieval_operator(
                    live_retrieval,
                    artifact_store=artifact_store,
                    corpus_store=research_corpus_store,
                )
                if live_retrieval is not None
                else None,
            ),
            live_model=_agent_uses_live_model(args),
        )
        payload = runtime.run(
            args.goal,
            mode=_agent_mode(args),
            planner_mode=_processor_mode(args, "planner"),
            evaluator_mode=_processor_mode(args, "evaluator"),
            synthesizer_mode=_processor_mode(args, "synthesizer"),
            semantic_mode=_processor_mode(args, "semantic_intake"),
            citations_required=True if args.citations_required else None,
            execution_metadata=_runtime_execution_metadata(args),
        )
        print(json.dumps(payload.to_dict(), ensure_ascii=False, sort_keys=True))
        return 0

    if args.command == "answer":
        runtime = _agent_runtime(
            journal,
            live_model=False,
            response_language=_response_language_for_args(args),
            artifact_store=_runtime_artifact_store(args),
            memory_store=_memory_store(args, create_default=True),
            research_corpus_store=_runtime_corpus_store(args),
        )
        payload = runtime.run(
            args.goal,
            mode="retrieval" if args.citations_required or args.research_profile else "auto",
            citations_required=True if args.citations_required else None,
            execution_metadata=_runtime_execution_metadata(args),
        )
        print(json.dumps(payload.to_dict(), ensure_ascii=False, sort_keys=True))
        return 0

    if args.command == "chat":
        live_block = _chat_live_model_block(args)
        if live_block is not None:
            if chat_output_mode(args, once=args.once is not None) == "human":
                print(
                    render_status_notice(
                        {
                            **live_block,
                            "message": "Default holo-v3 chat is live. Configure DEEPSEEK_API_KEY, or run an explicit offline/fake subcommand.",
                        },
                        color=chat_color_enabled(args),
                    )
                )
            else:
                print(json.dumps(live_block, sort_keys=True))
            return 1
        live_retrieval = _live_retrieval_config_for_args(args)
        if isinstance(live_retrieval, dict):
            print(json.dumps(live_retrieval, ensure_ascii=False, sort_keys=True))
            return 1
        artifact_store = _runtime_artifact_store(args)
        research_corpus_store = _runtime_corpus_store(args)
        runtime = _chat_runtime(
            journal,
            artifact_store=artifact_store,
            memory_store=_memory_store(args, create_default=True),
            research_corpus_store=research_corpus_store,
            retrieval_operator=_build_live_retrieval_operator(
                live_retrieval,
                artifact_store=artifact_store,
                corpus_store=research_corpus_store,
            )
            if live_retrieval is not None
            else None,
            thread_store=_thread_store(args, create_default=True),
            live_model=_agent_uses_live_model(args),
            model=args.model,
            profile=args.profile,
            thinking=_thinking_override(args.thinking),
            reasoning_effort=args.reasoning_effort,
            max_output_tokens=args.max_output_tokens,
            temperature=args.temperature,
            generation_mode=args.generation_mode,
            latency_target=args.latency_target,
            response_language=_response_language_for_args(args),
            planner_mode=_processor_mode(args, "planner"),
            evaluator_mode=_processor_mode(args, "evaluator"),
            synthesizer_mode=_processor_mode(args, "synthesizer"),
            semantic_mode=_processor_mode(args, "semantic_intake"),
            turn_router_mode=_processor_mode(args, "turn_router"),
            default_mode=_chat_default_mode(args),
            execution_metadata=_runtime_execution_metadata(args),
        )
        if args.once is not None:
            if chat_output_mode(args, once=True) == "human":
                payload = print_chat_turn_human(
                    runtime,
                    args.once,
                    thread_id=args.thread,
                    color=chat_color_enabled(args),
                )
            else:
                payload = runtime.receive(args.once, thread_id=args.thread)
                print(json.dumps(public_chat_result_payload(payload), ensure_ascii=False, sort_keys=True))
            return 0 if payload.status not in {"failed", "blocked"} else 1
        return run_chat_console(
            runtime,
            ChatConsoleOptions(
                thread=args.thread,
                output=args.output,
                color=args.color,
                no_color=args.no_color,
            ),
        )

    if args.command == "chat-status":
        runtime = _chat_runtime(
            journal,
            memory_store=_memory_store(args, create_default=True),
            thread_store=_thread_store(args, create_default=True),
        )
        print(json.dumps(runtime.build_thread_state(args.thread_id).to_dict(), ensure_ascii=False, sort_keys=True))
        return 0

    if args.command == "chat-summary":
        runtime = _chat_runtime(
            journal,
            memory_store=_memory_store(args, create_default=True),
            thread_store=_thread_store(args, create_default=True),
        )
        summary = runtime.summarize_thread(args.thread_id)
        print(json.dumps(summary.to_dict(), ensure_ascii=False, sort_keys=True))
        return 0

    if args.command == "memory":
        payload = _memory_command(args, journal)
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        return 0 if payload.get("status") != "failed" else 1

    if args.command == "resident":
        live_block = _chat_live_model_block(args) if getattr(args, "resident_command", None) in {"run", "run-once"} else None
        if live_block is not None:
            print(json.dumps(live_block, sort_keys=True))
            return 1
        payload = _resident_command(args, journal)
        if getattr(args, "output", "json") == "human":
            print(_resident_human_text(payload))
        else:
            print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        return 0 if payload.get("status") not in {"failed", "blocked", "error"} else 1

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
        live_retrieval = _live_retrieval_config_for_args(args)
        if isinstance(live_retrieval, dict):
            print(json.dumps(live_retrieval, ensure_ascii=False, sort_keys=True))
            return 1
        artifact_store = _artifact_store(
            args,
            create_default=bool(args.artifact_log or args.index_corpus or args.from_corpus or live_retrieval is not None),
        )
        corpus_store = _corpus_store(
            args,
            create_default=bool(args.corpus_log or args.index_corpus or args.from_corpus),
        )
        payload = _run_retrieve(
            journal,
            query=args.query,
            body=args.body,
            synthesizer_mode=args.synthesizer,
            artifact_store=artifact_store,
            corpus_store=corpus_store,
            retrieval_operator=_build_live_retrieval_operator(
                live_retrieval,
                artifact_store=artifact_store,
                corpus_store=corpus_store,
            )
            if live_retrieval is not None
            else None,
            source_uri=args.uri,
            source_title=args.title,
            research_profile_id=args.profile,
            max_queries=args.max_queries,
            max_sources=args.max_sources,
            max_fetches=args.max_fetches,
            max_spans_per_document=args.max_spans_per_document,
            from_corpus=args.from_corpus,
            index_corpus=args.index_corpus,
        )
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        return 0

    if args.command == "retrieval-providers":
        payload = _retrieval_provider_command(args)
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        return 0 if payload.get("status") not in {"failed", "error", "blocked"} else 1

    if args.command == "corpus":
        payload = _corpus_command(args)
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        return 0 if payload.get("status") != "failed" else 1

    if args.command == "sources":
        payload = _sources_command(args)
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        return 0 if payload.get("status") != "failed" else 1

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

    if args.command == "retrieval-benchmark":
        print(json.dumps(retrieval_behavior_benchmark(journal, args.task_id), ensure_ascii=False, sort_keys=True))
        return 0

    if args.command == "behavior-graph":
        graph = BehaviorGraphBuilder(journal).build_task_graph(args.task_id, max_nodes=args.max_nodes)
        if args.format == "dot":
            rendered = render_behavior_graph_dot(graph)
        else:
            rendered = json.dumps(graph.to_dict(), ensure_ascii=False, sort_keys=True, indent=2)
        if args.output:
            path = Path(args.output)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(rendered + "\n", encoding="utf-8")
        else:
            print(rendered)
        return 0

    if args.command == "bench":
        payload = _bench_command(args, journal)
        raw_output = payload.pop("_stdout", None)
        if isinstance(raw_output, str):
            print(raw_output)
            return 0 if payload.get("status") not in {"failed", "blocked", "error"} else 1
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        return 0 if payload.get("status") not in {"failed", "blocked", "error"} else 1

    if args.command == "memory-trace":
        print(TraceRenderer(journal).render_memory_trace(args.task_id))
        return 0
    if args.command == "resident-trace":
        print(TraceRenderer(journal).render_resident_trace(limit=args.limit))
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

    if args.command == "model-packet":
        print(json.dumps(_model_packet_payload(args), ensure_ascii=False, sort_keys=True))
        return 0

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
            max_output_tokens=args.max_output_tokens,
            temperature=args.temperature,
            generation_mode=args.generation_mode,
            latency_target=args.latency_target,
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
            max_output_tokens=args.max_output_tokens,
            temperature=args.temperature,
            generation_mode=args.generation_mode,
            latency_target=args.latency_target,
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
    if not argv:
        return ["chat", "--output", "human"]
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
    max_output_tokens: object = "provider",
    temperature: float | None = None,
    generation_mode: str = "auto",
    latency_target: str = "balanced",
    response_language: str | None = None,
    artifact_store: ArtifactStore | None = None,
    memory_store: MemoryStore | None = None,
    research_corpus_store: ResearchCorpusStore | None = None,
    retrieval_operator: RetrievalOperator | None = None,
) -> AgentRuntime:
    fabric = (
        _live_processor_fabric(
            "deepseek",
            journal,
            model=model,
            profile=profile,
            thinking=thinking,
            reasoning_effort=reasoning_effort,
            max_output_tokens=max_output_tokens,
            temperature=temperature,
            generation_mode=generation_mode,
            latency_target=latency_target,
        )
        if live_model
        else None
    )
    return AgentRuntime(
        journal=journal,
        artifact_store=artifact_store,
        processor_fabric=fabric,
        retrieval_operator=retrieval_operator,
        workspace_root=Path.cwd(),
        memory_store=memory_store,
        research_corpus_store=research_corpus_store,
        response_language=normalize_response_language(response_language),
    )


def _mission_runtime(runtime: AgentRuntime, *, live_model: bool) -> MissionRuntime:
    return MissionRuntime(
        agent_runtime=runtime,
        assessor_mode="model" if live_model else "rule",
        max_iterations=6,
    )


def _chat_runtime(
    journal: JournalStore,
    *,
    artifact_store: ArtifactStore | None = None,
    memory_store: MemoryStore | None = None,
    research_corpus_store: ResearchCorpusStore | None = None,
    retrieval_operator: RetrievalOperator | None = None,
    thread_store: ThreadTranscriptStore | None = None,
    live_model: bool = False,
    model: str | None = None,
    profile: str = "balanced",
    thinking: str | None = None,
    reasoning_effort: str = "high",
    max_output_tokens: object = "provider",
    temperature: float | None = None,
    generation_mode: str = "auto",
    latency_target: str = "balanced",
    response_language: str | None = None,
    planner_mode: str = "fake",
    evaluator_mode: str = "fake",
    synthesizer_mode: str = "fake",
    semantic_mode: str = "fake",
    turn_router_mode: str = "fake",
    default_mode: str = "auto",
    execution_metadata: JsonObject | None = None,
    mission_enabled: bool = True,
) -> ChatRuntime:
    agent_runtime = _agent_runtime(
        journal,
        live_model=live_model,
        model=model,
        profile=profile,
        thinking=thinking,
        reasoning_effort=reasoning_effort,
        max_output_tokens=max_output_tokens,
        temperature=temperature,
        generation_mode=generation_mode,
        latency_target=latency_target,
        response_language=response_language,
        artifact_store=artifact_store,
        memory_store=memory_store,
        research_corpus_store=research_corpus_store,
        retrieval_operator=retrieval_operator,
    )
    return ChatRuntime(
        journal=journal,
        agent_runtime=_mission_runtime(agent_runtime, live_model=live_model) if mission_enabled else agent_runtime,
        memory_store=memory_store,
        planner_mode=planner_mode,
        evaluator_mode=evaluator_mode,
        synthesizer_mode=synthesizer_mode,
        semantic_mode=semantic_mode,
        turn_router_mode=turn_router_mode,
        default_mode=default_mode,
        execution_metadata=execution_metadata,
        thread_store=thread_store,
    )


def _memory_store(args, *, create_default: bool) -> MemoryStore | None:
    memory_log = getattr(args, "memory_log", None)
    memory_index = getattr(args, "memory_index", None)
    if memory_log is None and not create_default:
        return None
    log_path = Path(memory_log) if memory_log is not None else default_memory_log_path()
    index_path = Path(memory_index) if memory_index is not None else default_memory_index_path()
    return MemoryStore(log_path, index_path=index_path)


def _thread_store(args, *, create_default: bool) -> ThreadTranscriptStore | None:
    root = getattr(args, "thread_store_root", None)
    if root is None and not create_default:
        return None
    if root is not None:
        return ThreadTranscriptStore(root)
    journal_path = Path(getattr(args, "journal", default_journal_path()))
    if journal_path != default_journal_path():
        return ThreadTranscriptStore(journal_path.parent / "threads")
    return ThreadTranscriptStore(default_thread_root())


def _runtime_artifact_store(args) -> ArtifactStore | None:
    return _artifact_store(
        args,
        create_default=bool(getattr(args, "artifact_log", None)) or _corpus_configured(args),
    )


def _runtime_corpus_store(args) -> ResearchCorpusStore | None:
    return _corpus_store(args, create_default=_corpus_configured(args))


def _runtime_execution_metadata(args) -> JsonObject | None:
    metadata: JsonObject = {}
    response_language = _response_language_for_args(args)
    execution = _execution_profile_for_args(args)
    if execution is not None:
        metadata.update(execution_profile_runtime_metadata(execution))
    metadata["interaction_preferences"] = {
        "response_language": response_language,
    }
    metadata["context_budget"] = merge_context_budget(
        _context_profile_for_args(args, execution),
        token_budget=getattr(args, "context_token_budget", None),
        section_budget=getattr(args, "context_section_budget", None),
        workspace_evidence_chars=getattr(args, "workspace_evidence_chars", None),
        synthesis_evidence_preview_chars=getattr(args, "synthesis_evidence_preview_chars", None),
    )
    loop_budget: JsonObject = {}
    if getattr(args, "max_agent_steps", None) is not None:
        loop_budget["max_steps"] = _positive_limit(getattr(args, "max_agent_steps"), default=1)
    if getattr(args, "max_agent_tool_calls", None) is not None:
        loop_budget["max_tool_calls"] = _positive_limit(getattr(args, "max_agent_tool_calls"), default=1)
    if getattr(args, "max_agent_artifact_bytes", None) is not None:
        loop_budget["max_total_artifact_bytes"] = _positive_limit(getattr(args, "max_agent_artifact_bytes"), default=1)
    if loop_budget:
        current_loop = metadata.get("agent_loop")
        current_loop = dict(current_loop) if isinstance(current_loop, dict) else {}
        metadata["agent_loop"] = {**current_loop, **loop_budget}
    research_profile = getattr(args, "research_profile", None)
    if isinstance(research_profile, str) and research_profile:
        research_depth = _research_depth_for_args(args, execution)
        retrieval = metadata.setdefault("retrieval", {})
        current_metadata = retrieval.get("metadata")
        current_metadata = dict(current_metadata) if isinstance(current_metadata, dict) else {}
        retrieval["metadata"] = {
            **current_metadata,
            "research_profile": research_profile,
            "research_depth": research_depth,
        }
        for key, value in research_depth_defaults(research_profile, research_depth).items():
            retrieval.setdefault(key, value)
        if execution is not None:
            retrieval["max_queries"] = execution.max_queries
            retrieval["max_sources"] = execution.max_sources
            retrieval["max_fetches"] = execution.max_fetches
            retrieval["max_spans_per_document"] = execution.max_spans_per_document
            retrieval["max_retrieval_runs"] = execution.max_retrieval_runs
            retrieval_metadata = retrieval.get("metadata")
            retrieval_metadata = dict(retrieval_metadata) if isinstance(retrieval_metadata, dict) else {}
            retrieval["metadata"] = {
                **retrieval_metadata,
                "execution_profile": execution.profile_id,
                "retrieval_mode": execution.retrieval_mode,
            }
    if _live_retrieval_requested(args):
        retrieval = metadata.setdefault("retrieval", {})
        retrieval["allow_network"] = True
        total_budget = _positive_limit(getattr(args, "live_max_network_fetches", 3), default=3)
        retrieval["max_network_fetches"] = total_budget
        max_queries = _positive_limit(retrieval.get("max_queries"), default=0) if "max_queries" in retrieval else 0
        per_action_fetch_default = min(total_budget, DEFAULT_LIVE_RETRIEVAL_FETCH_BUDGET)
        requested_fetches = (
            _positive_limit(retrieval.get("max_fetches"), default=per_action_fetch_default)
            if "max_fetches" in retrieval
            else per_action_fetch_default
        )
        remaining_fetch_budget = max(1, total_budget - max_queries) if max_queries else total_budget
        retrieval["max_fetches"] = min(requested_fetches, remaining_fetch_budget)
        if max_queries:
            retrieval["network_fetch_count"] = max_queries + int(retrieval["max_fetches"])
    return metadata or None


def _execution_profile_for_args(args) -> ExecutionProfile | None:
    profile_id = getattr(args, "execution_profile", None)
    if not profile_id:
        return None
    return execution_profile(str(profile_id))


def _context_profile_for_args(args, execution: ExecutionProfile | None) -> str:
    if execution is not None:
        current = str(getattr(args, "context_profile", "") or "")
        if not current or current == DEFAULT_LIVE_CONTEXT_PROFILE:
            return execution.context_profile
    return str(getattr(args, "context_profile", "compact") or "compact")


def _research_depth_for_args(args, execution: ExecutionProfile | None) -> str:
    if execution is not None:
        current = str(getattr(args, "research_depth", "") or "")
        if not current or current == DEFAULT_RESEARCH_DEPTH:
            return execution.research_depth
    return str(getattr(args, "research_depth", "balanced") or "balanced")


def _benchmark_processor_mode(args, name: str, execution: ExecutionProfile | None) -> str:
    if execution is not None:
        return profile_processor_mode(
            execution,
            name,
            str(getattr(args, name, "fake")),
            online=bool(getattr(args, "online", False)),
        )
    return _processor_mode(args, name)


def _mission_enabled_for_args(args, execution: ExecutionProfile | None) -> bool:
    if execution is None:
        return True
    return profile_mission_enabled(execution, requested=str(getattr(args, "mission", "auto") or "auto"))


def _response_language_for_args(args) -> str:
    return normalize_response_language(getattr(args, "response_language", None) or os.environ.get("HOLO_V3_RESPONSE_LANGUAGE"))


def _live_retrieval_requested(args) -> bool:
    explicit = getattr(args, "live_retrieval", None)
    if explicit is not None:
        return bool(explicit)
    return _live_retrieval_auto_enabled(args)


def _live_retrieval_explicitly_enabled(args) -> bool:
    return getattr(args, "live_retrieval", None) is True


def _live_retrieval_auto_enabled(args) -> bool:
    command = str(getattr(args, "command", "") or "")
    if command in {"agent", "chat"}:
        return _agent_uses_live_model(args)
    if command == "resident" and str(getattr(args, "resident_command", "") or "") in {"run", "run-once"}:
        return _agent_uses_live_model(args)
    return False


def _live_retrieval_config_for_args(args) -> LiveRetrievalConfig | JsonObject | None:
    if not _live_retrieval_requested(args):
        return None
    config = _live_retrieval_config_from_args(args, enable=True)
    allowed_host_issues = _live_retrieval_allowed_host_issues(config)
    if allowed_host_issues:
        return {
            "status": "blocked",
            "reason": "live_retrieval_allowed_hosts_not_configured",
            "live_config": config.safe_diagnostics(),
            "issues": allowed_host_issues,
        }
    return config


def _live_retrieval_config_from_args(args, *, enable: bool) -> LiveRetrievalConfig:
    env = dict(os.environ)
    if enable:
        env[LIVE_RETRIEVAL_ENV] = "1"
    if enable and _live_retrieval_needs_default_web_discovery(args, env):
        env[LIVE_WEB_SEARCH_PROVIDERS_ENV] = DEFAULT_LIVE_WEB_SEARCH_PROVIDERS
        env.setdefault(LIVE_SEARCH_STRATEGY_ENV, DEFAULT_LIVE_SEARCH_STRATEGY)
        env.setdefault(LIVE_FETCH_DISCOVERED_SEARCH_HOSTS_ENV, "1")
    if enable:
        env.setdefault(LIVE_SOURCE_DIRECTORY_ALLOWLIST_ENV, "1")
    if bool(getattr(args, "live_allow_all_hosts", False)):
        env[LIVE_ALLOW_ALL_HOSTS_ENV] = "1"
    _set_optional_env(env, LIVE_SEARCH_ENDPOINT_ENV, getattr(args, "live_search_endpoint", None))
    _merge_csv_env(env, LIVE_WEB_SEARCH_PROVIDERS_ENV, _cli_csv_values(getattr(args, "live_web_search_provider", None)))
    _set_positive_env(
        env,
        LIVE_WEB_SEARCH_MAX_RESULTS_PER_ENGINE_ENV,
        getattr(args, "live_web_search_max_results_per_engine", None),
    )
    fetch_discovered = getattr(args, "live_fetch_discovered_search_hosts", None)
    if fetch_discovered is True:
        env[LIVE_FETCH_DISCOVERED_SEARCH_HOSTS_ENV] = "1"
    elif fetch_discovered is False:
        env[LIVE_FETCH_DISCOVERED_SEARCH_HOSTS_ENV] = "0"
    _merge_csv_env(env, LIVE_SEARCH_ALLOWED_HOSTS_ENV, _cli_csv_values(getattr(args, "live_search_allowed_host", None)))
    _merge_csv_env(env, LIVE_FETCH_ALLOWED_HOSTS_ENV, _cli_csv_values(getattr(args, "live_fetch_allowed_host", None)))
    _merge_csv_env(env, LIVE_CRAWL_SEED_URLS_ENV, _cli_csv_values(getattr(args, "live_crawl_seed_url", None)))
    if bool(getattr(args, "live_crawl_source_directory", False)):
        env[LIVE_CRAWL_SOURCE_DIRECTORY_ENV] = "1"
    if bool(getattr(args, "live_source_directory_allowlist", False)):
        env[LIVE_SOURCE_DIRECTORY_ALLOWLIST_ENV] = "1"
    if bool(getattr(args, "live_crawl_include_sitemaps", True)) is False:
        env[LIVE_CRAWL_INCLUDE_SITEMAPS_ENV] = "0"
    _set_positive_env(env, LIVE_CRAWL_MAX_PAGES_ENV, getattr(args, "live_crawl_max_pages", None))
    _set_positive_env(env, LIVE_CRAWL_MAX_LINKS_PER_PAGE_ENV, getattr(args, "live_crawl_max_links_per_page", None))
    _set_positive_env(env, LIVE_CRAWL_MAX_SITEMAP_URLS_ENV, getattr(args, "live_crawl_max_sitemap_urls", None))
    _set_positive_env(
        env,
        LIVE_CRAWL_MAX_SOURCE_DIRECTORY_SEEDS_ENV,
        getattr(args, "live_crawl_max_source_directory_seeds", None),
    )
    _set_optional_env(env, LIVE_SEARCH_STRATEGY_ENV, getattr(args, "live_search_strategy", None))
    _set_positive_env(
        env,
        LIVE_SEARCH_MAX_SOURCES_PER_PROVIDER_ENV,
        getattr(args, "live_search_max_sources_per_provider", None),
    )
    _set_positive_env(env, LIVE_TIMEOUT_SECONDS_ENV, getattr(args, "live_timeout_seconds", None))
    _set_positive_env(env, LIVE_MAX_BYTES_ENV, getattr(args, "live_max_bytes", None))
    _set_positive_env(env, LIVE_DOWNLOAD_BYTE_BUDGET_ENV, getattr(args, "live_download_byte_budget", None))
    if getattr(args, "live_cache_dir", None) is not None:
        env[LIVE_CACHE_DIR_ENV] = str(getattr(args, "live_cache_dir") or "")
    return LiveRetrievalConfig.from_env(env)


def _live_retrieval_needs_default_web_discovery(args, env: dict[str, str]) -> bool:
    if _env_optional(env.get(LIVE_SEARCH_ENDPOINT_ENV)) or _env_optional(getattr(args, "live_search_endpoint", None)):
        return False
    if _env_csv(env.get(LIVE_WEB_SEARCH_PROVIDERS_ENV)) or _cli_csv_values(getattr(args, "live_web_search_provider", None)):
        return False
    if _env_csv(env.get(LIVE_CRAWL_SEED_URLS_ENV)) or _cli_csv_values(getattr(args, "live_crawl_seed_url", None)):
        return False
    if _env_truthy(env.get(LIVE_CRAWL_SOURCE_DIRECTORY_ENV)) or bool(getattr(args, "live_crawl_source_directory", False)):
        return False
    return True


def _env_optional(value: object) -> str:
    return str(value or "").strip()


def _env_csv(value: object) -> list[str]:
    text = str(value or "")
    return [part.strip() for part in text.split(",") if part.strip()]


def _env_truthy(value: object) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _set_optional_env(env: dict[str, str], name: str, value: object) -> None:
    text = str(value or "").strip()
    if text:
        env[name] = text


def _set_positive_env(env: dict[str, str], name: str, value: object) -> None:
    try:
        parsed = int(str(value or "").strip())
    except ValueError:
        return
    if parsed > 0:
        env[name] = str(parsed)


def _merge_csv_env(env: dict[str, str], name: str, values: list[str]) -> None:
    if not values:
        return
    existing = [part.strip() for part in str(env.get(name, "") or "").split(",") if part.strip()]
    env[name] = ",".join(_ordered_unique([*existing, *values]))


def _cli_csv_values(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    values: list[str] = []
    for item in value:
        values.extend(part.strip() for part in str(item or "").split(",") if part.strip())
    return values


def _ordered_unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _build_live_retrieval_operator(
    config: LiveRetrievalConfig,
    *,
    artifact_store: ArtifactStore | None,
    corpus_store: ResearchCorpusStore | None,
) -> RetrievalOperator:
    parameters = inspect.signature(config.build_operator).parameters
    if "artifact_store" in parameters or "corpus_store" in parameters:
        return config.build_operator(
            artifact_store=artifact_store,
            corpus_store=corpus_store,
        )
    return config.build_operator()


def _live_retrieval_doctor_config(args) -> JsonObject:
    if not _live_retrieval_requested(args):
        return {"requested": False, "config": None, "issues": [], "operator": None}
    config = _live_retrieval_config_from_args(args, enable=True)
    issues: list[JsonObject] = []
    operator: RetrievalOperator | None = None
    issues.extend(_live_retrieval_allowed_host_issues(config))
    operator = config.build_operator()
    return {
        "requested": True,
        "config": config.safe_diagnostics(),
        "issues": issues,
        "operator": operator,
    }


def _live_retrieval_doctor_status(issues: list[JsonObject]) -> str:
    severities = {str(issue.get("severity") or "attention") for issue in issues}
    if "error" in severities:
        return "error"
    if "warning" in severities:
        return "warning"
    if "attention" in severities:
        return "attention"
    return "ok"


def _live_retrieval_allowed_host_issues(config: LiveRetrievalConfig) -> list[JsonObject]:
    issues: list[JsonObject] = []
    if (
        config.search.configured
        and not config.search.allow_all_hosts
        and (
            not config.search.allowed_hosts
            or not _url_host_allowed(config.search.endpoint_url, config.search.allowed_hosts)
        )
    ):
        issues.append(
            {
                "component": "retrieval",
                "severity": "error",
                "code": "live_provider_without_allowed_hosts",
                "provider_id": "live_json_http_search",
                "provider_kind": "search",
            }
        )
    if config.web_search.configured and not config.web_search.allow_all_hosts and not config.web_search.allowed_hosts:
        issues.append(
            {
                "component": "retrieval",
                "severity": "error",
                "code": "live_provider_without_allowed_hosts",
                "provider_id": "live_web_search",
                "provider_kind": "search",
            }
        )
    if config.crawl.configured and not config.crawl.allow_all_hosts and not config.crawl.allowed_hosts:
        issues.append(
            {
                "component": "retrieval",
                "severity": "error",
                "code": "live_provider_without_allowed_hosts",
                "provider_id": "bounded_crawl_search",
                "provider_kind": "search",
            }
        )
    if (
        not config.fetch.allow_all_hosts
        and not config.fetch.allowed_hosts
        and not config.fetch.allow_discovered_search_hosts
    ):
        issues.append(
            {
                "component": "retrieval",
                "severity": "error",
                "code": "live_provider_without_allowed_hosts",
                "provider_id": "live_http_fetch",
                "provider_kind": "fetch",
            }
        )
    return issues


def _url_host_allowed(url: str | None, allowed_hosts: list[str]) -> bool:
    host = urllib.parse.urlparse(str(url or "")).hostname
    if not host:
        return False
    return any(_host_matches(host.lower(), str(allowed).strip().lower()) for allowed in allowed_hosts)


def _host_matches(host: str, allowed: str) -> bool:
    if not allowed:
        return False
    if allowed.startswith("*."):
        suffix = allowed[1:]
        return host.endswith(suffix) and host != allowed[2:]
    return host == allowed


def _artifact_store(args, *, create_default: bool) -> ArtifactStore | None:
    artifact_log = getattr(args, "artifact_log", None)
    if artifact_log is None and not create_default:
        return None
    return ArtifactStore(Path(artifact_log or "kernel_v3/.holo-v3-artifacts.jsonl"))


def _corpus_store(args, *, create_default: bool) -> ResearchCorpusStore | None:
    corpus_log = getattr(args, "corpus_log", None)
    corpus_index = getattr(args, "corpus_index", None)
    if corpus_log is None and not create_default:
        return None
    log_path = Path(corpus_log or "kernel_v3/.holo-v3-corpus.jsonl")
    index_path = Path(corpus_index) if corpus_index is not None else log_path.with_suffix(".sqlite")
    return ResearchCorpusStore(log_path=log_path, index_path=index_path)


def _corpus_configured(args) -> bool:
    return bool(getattr(args, "corpus_log", None) or getattr(args, "corpus_index", None))


def _memory_configured(args) -> bool:
    return bool(getattr(args, "memory_log", None) or getattr(args, "memory_index", None))


def _corpus_command(args) -> dict[str, object]:
    store = _corpus_store(args, create_default=True)
    if store is None:
        return {"status": "failed", "reason": "corpus_store_not_configured"}
    command = args.corpus_command
    if command == "list":
        documents = store.documents(profile_id=args.profile)[: _positive_limit(args.limit)]
        return {"status": "ok", "documents": [document.to_dict() for document in documents]}
    if command == "search":
        result = store.search(
            args.query,
            profile_id=args.profile,
            limit=_positive_limit(args.limit),
            record_access=True,
            access_context={
                "surface": "cli",
                "command": "corpus search",
                "profile_id": args.profile,
            },
        )
        return {
            "status": "ok",
            "result": result.to_dict(),
        }
    if command == "inspect":
        document = store.get(args.document_id)
        if document is None:
            return {"status": "failed", "reason": "corpus_document_not_found", "document_id": args.document_id}
        return {"status": "ok", "document": document.to_dict()}
    if command == "audit":
        records = store.audit_records()[-_positive_limit(args.limit) :]
        return {"status": "ok", "records": records}
    if command == "status":
        return {"status": "ok", "corpus": store.status().to_dict()}
    if command == "inspect-store":
        inspection = store.inspect(
            sample_limit=args.sample_limit,
            artifact_store=_artifact_store(args, create_default=False),
            profile_id=args.profile,
        )
        return {"status": inspection.status, "inspection": inspection.to_dict()}
    if command == "index":
        return {"status": "ok", "documents": store.index_documents()}
    return {"status": "failed", "reason": f"unknown_corpus_command:{command}"}


def _sources_command(args) -> dict[str, object]:
    profile_id = getattr(args, "profile", None) or FINANCE_FUNDAMENTALS_PROFILE_ID
    command = args.sources_command
    if command == "list":
        return site_index_list(
            profile_id=profile_id,
            authority=getattr(args, "authority", None),
            family=getattr(args, "family", None),
            source_id=getattr(args, "source_id", None),
            limit=getattr(args, "limit", 100),
        )
    if command == "seeds":
        return site_index_seeds(
            profile_id=profile_id,
            authority=getattr(args, "authority", None),
            family=getattr(args, "family", None),
            source_id=getattr(args, "source_id", None),
            limit=getattr(args, "limit", 100),
        )
    if command == "families":
        return site_index_families(profile_id=profile_id)
    if command == "plan":
        return site_index_plan(
            profile_id=profile_id,
            query=args.query,
            authority=getattr(args, "authority", None),
            family=getattr(args, "family", None),
            limit=getattr(args, "limit", 12),
        )
    return {"status": "failed", "reason": f"unknown_sources_command:{command}"}


def _memory_command(args, journal: JournalStore) -> dict[str, object]:
    store = _memory_store(args, create_default=True)
    if store is None:
        return {"status": "failed", "reason": "memory_store_not_configured"}
    command = args.memory_command
    if command == "list":
        scope = {"thread_id": args.thread} if args.thread else None
        result = store.recall(
            query=args.query,
            scope=scope,
            record_access=True,
            access_context={
                "surface": "cli",
                "command": "memory list",
                **({"thread_id": args.thread} if args.thread else {}),
            },
        )
        return {"status": "ok", "result": result.to_dict()}
    if command == "proposals":
        proposals = [proposal.to_dict() for proposal in store.proposals()]
        if args.thread:
            proposals = [proposal for proposal in proposals if proposal.get("source_thread_id") == args.thread]
        return {"status": "ok", "proposals": proposals}
    if command == "inspect":
        inspection = store.inspect(
            sample_limit=args.sample_limit,
            journal=journal,
            artifact_store=_artifact_store(args, create_default=False),
        )
        return {"status": inspection.status, "inspection": inspection.to_dict()}
    pipeline = MemoryPipeline(store=store, journal=journal)
    if command == "propose":
        result = pipeline.propose_from_semantic_intake(
            _explicit_memory_intake(args.text),
            task_id="task-cli-memory",
            run_id="run-cli-memory",
            thread_id=args.thread,
            source_record_ref=None,
        )
        return {"status": "ok", "result": result.to_dict()}
    if command == "approve":
        try:
            result = pipeline.approve_proposal(args.proposal_id, approved_by="user")
            return {"status": "ok", "result": result.to_dict()}
        except (KeyError, ValueError) as exc:
            return _memory_command_failure(journal, command=command, target_id=args.proposal_id, error=_exception_reason(exc))
    if command == "reject":
        try:
            result = pipeline.reject_proposal(args.proposal_id, reason=args.reason)
            return {"status": "ok", "result": result.to_dict()}
        except (KeyError, ValueError) as exc:
            return _memory_command_failure(journal, command=command, target_id=args.proposal_id, error=_exception_reason(exc))
    if command == "delete":
        try:
            tombstone = pipeline.delete_memory(
                args.memory_id,
                reason=args.reason,
                deleted_by="user",
                task_id="task-cli-memory",
                run_id="run-cli-memory",
            )
            return {"status": "ok", "tombstone": tombstone.to_dict()}
        except (KeyError, ValueError) as exc:
            return _memory_command_failure(journal, command=command, target_id=args.memory_id, error=_exception_reason(exc))
    if command == "export":
        try:
            export = store.export_item(
                args.memory_id,
                record_access=True,
                access_context={
                    "surface": "cli",
                    "command": "memory export",
                    "target_id": args.memory_id,
                },
            )
            return {"status": "ok", "export": export}
        except (KeyError, ValueError) as exc:
            return _memory_command_failure(journal, command=command, target_id=args.memory_id, error=_exception_reason(exc))
    if command == "migrate-semantic":
        from kernel_v3.memory.migration import migrate_semantic_intake_records

        report = migrate_semantic_intake_records(journal=journal, store=store, limit=args.limit)
        return {"status": "ok", "migration": report.to_dict()}
    return {"status": "failed", "reason": f"unknown_memory_command:{command}"}


def _memory_command_failure(
    journal: JournalStore,
    *,
    command: str,
    target_id: str,
    error: str,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "status": "failed",
        "reason": error,
        "command": command,
        "target_id": target_id,
    }
    journal.append(
        task_id="task-cli-memory",
        run_id="run-cli-memory",
        step_id=None,
        kind="memory_command_failed",
        data=payload,
        state_delta={"memory_command": command, "memory_command_status": "failed"},
    )
    return payload


def _explicit_memory_intake(text: str) -> SemanticIntake:
    return SemanticIntake(
        intake_id="semantic-intake-cli-memory",
        goal=text,
        primary_intent="memory_write",
        suggested_mode="clarify_first",
        compound=False,
        requires_clarification=True,
        intents=[
            {
                "kind": "memory_write",
                "text": text,
                "sequence_index": 1,
                "required_capabilities": ["durable_memory:write"],
                "risk": "write",
                "status": "needs_review",
                "metadata": {"source": "cli_memory_propose"},
            }
        ],
        blocked_capabilities=["durable_memory:write"],
        warnings=[],
        response_hint=None,
        clarification_question=None,
    )


def _resident_queue(args) -> ResidentQueue:
    db_path = Path(getattr(args, "resident_db", None) or "kernel_v3/.holo-v3-resident.sqlite")
    return ResidentQueue(db_path)


def _bench_command(args, journal: JournalStore) -> dict[str, object]:
    command = str(getattr(args, "bench_command", "") or "")
    if command == "general":
        runtime = None
        if getattr(args, "live", False):
            live_block = _chat_live_model_block(args)
            if live_block is not None:
                return {
                    **live_block,
                    "benchmark": "general",
                    "message": "General live gauntlet requires the model stack. Omit --live for the contract-only host capability gauntlet.",
                }
            live_retrieval = _live_retrieval_config_for_args(args)
            if isinstance(live_retrieval, dict):
                return live_retrieval
            artifact_store = _runtime_artifact_store(args)
            research_corpus_store = _runtime_corpus_store(args)
            runtime = _chat_runtime(
                journal,
                artifact_store=artifact_store,
                memory_store=_memory_store(args, create_default=True),
                research_corpus_store=research_corpus_store,
                retrieval_operator=_build_live_retrieval_operator(
                    live_retrieval,
                    artifact_store=artifact_store,
                    corpus_store=research_corpus_store,
                )
                if live_retrieval is not None
                else None,
                thread_store=_thread_store(args, create_default=True),
                live_model=_agent_uses_live_model(args),
                model=args.model,
                profile=args.profile,
                thinking=_thinking_override(args.thinking),
                reasoning_effort=args.reasoning_effort,
                max_output_tokens=args.max_output_tokens,
                temperature=args.temperature,
                generation_mode=args.generation_mode,
                latency_target=args.latency_target,
                response_language=_response_language_for_args(args),
                planner_mode=args.planner,
                evaluator_mode=args.evaluator,
                synthesizer_mode=args.synthesizer,
                semantic_mode=args.semantic_intake,
                turn_router_mode=args.turn_router,
                default_mode="auto",
                execution_metadata=_runtime_execution_metadata(args),
                mission_enabled=False,
            )
        report = run_general_capability_gauntlet(runtime=runtime, thread_prefix=args.thread_prefix)
        outputs = write_general_capability_gauntlet_outputs(
            report,
            output_path=args.output,
            summary_path=args.summary_output,
            jsonl_path=args.jsonl_output,
        )
        return {
            "status": report["status"],
            "mode": "live_holo" if runtime is not None else "contract_gauntlet",
            "summary": report["summary"],
            **outputs,
        }
    if command == "finance-fetch":
        fetch_summary = fetch_public_finance_benchmark(
            benchmark=args.benchmark,
            output_path=args.output,
            split=args.split,
            source_url=args.url,
            timeout=args.timeout,
            max_bytes=args.max_bytes,
        )
        import_summary = None
        annotation_summary = None
        if getattr(args, "normalized_output", None):
            import_summary_obj = convert_public_finance_benchmark(
                benchmark=args.benchmark,
                input_path=args.output,
                output_path=args.normalized_output,
                manifest_path=args.manifest_output,
                limit=args.limit,
                offset=args.offset,
                mode=args.mode,
            )
            import_summary = import_summary_obj.to_dict()
            if getattr(args, "annotation_output", None):
                annotation_summary = write_finance_dev_annotations_from_dataset(
                    dataset_path=args.normalized_output,
                    annotation_path=args.annotation_output,
                )
            fetch_summary = replace(
                fetch_summary,
                imported_output_path=args.normalized_output,
                manifest_path=args.manifest_output,
                annotation_path=args.annotation_output,
                import_summary=import_summary,
            )
        journal.append(
            task_id=None,
            run_id="finance-benchmark-fetch",
            step_id=None,
            kind="finance_benchmark_fetch",
            data={**fetch_summary.to_dict(), "annotation_export": annotation_summary},
            state_delta={"finance_benchmark_fetch_status": fetch_summary.status, "finance_benchmark": fetch_summary.benchmark},
        )
        return {
            "status": "ok",
            "mode": "finance_fetch",
            "summary": fetch_summary.to_dict(),
            "import_summary": import_summary,
            "annotation_export": annotation_summary,
        }
    if command == "finance-import":
        summary = convert_public_finance_benchmark(
            benchmark=args.benchmark,
            input_path=args.input,
            output_path=args.output,
            manifest_path=args.manifest_output,
            limit=args.limit,
            offset=args.offset,
            mode=args.mode,
        )
        annotation_summary = None
        if getattr(args, "annotation_output", None):
            annotation_summary = write_finance_dev_annotations_from_dataset(
                dataset_path=args.output,
                annotation_path=args.annotation_output,
            )
        journal.append(
            task_id=None,
            run_id="finance-benchmark-import",
            step_id=None,
            kind="finance_benchmark_import",
            data={**summary.to_dict(), "annotation_export": annotation_summary},
            state_delta={"finance_benchmark_import_status": summary.status, "finance_benchmark_items": summary.item_count},
        )
        return {"status": "ok", "mode": "finance_import", "summary": summary.to_dict(), "annotation_export": annotation_summary}
    if command == "finance-graph":
        graph = build_benchmark_result_graph_from_path(
            args.results,
            benchmark_id=args.benchmark_id,
            max_items=args.max_items,
        )
        if args.format == "dot":
            rendered = render_behavior_graph_dot(graph)
        else:
            rendered = json.dumps(graph.to_dict(), ensure_ascii=False, sort_keys=True, indent=2)
        if args.output:
            path = Path(args.output)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(rendered + "\n", encoding="utf-8")
            output = str(path)
            stdout = None
        else:
            stdout = rendered
            output = None
        return {
            "status": "ok",
            "mode": "finance_graph",
            "schema": graph.schema,
            "diagnostics": graph.diagnostics,
            "output": output,
            "_stdout": stdout,
        }
    if command == "finance-report":
        report = build_finance_benchmark_report_from_path(
            args.results,
            benchmark_id=args.benchmark_id,
            title=args.title,
            max_weak_items=args.max_weak_items,
        )
        rendered = render_finance_benchmark_report(report, output_format=args.format)
        if args.output:
            path = Path(args.output)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(rendered, encoding="utf-8")
            output = str(path)
            stdout = None
        else:
            output = None
            stdout = rendered
        return {
            "status": "ok",
            "mode": "finance_report",
            "schema": report.schema,
            "summary": report.summary,
            "output": output,
            "_stdout": stdout,
        }
    if command == "finance-progress":
        payload = _finance_progress_command(args, journal)
        if getattr(args, "format", "text") == "text":
            return {**payload, "_stdout": _render_finance_progress(payload)}
        return payload
    if command != "finance":
        return {"status": "failed", "reason": "unknown_benchmark", "benchmark": command}
    output_path = Path(args.output) if args.output else None
    summary_path = Path(args.summary_output) if args.summary_output else None
    if getattr(args, "predictions", None):
        results = score_finance_prediction_file(
            dataset_path=args.dataset,
            predictions_path=args.predictions,
            limit=args.limit,
            offset=args.offset,
        )
        summary = write_finance_benchmark_outputs(
            results,
            output_path=output_path,
            summary_path=summary_path,
            annotation_path=args.dev_gold,
            journal=journal,
        )
        return {
            "status": "ok",
            "mode": "score_predictions",
            "summary": summary.to_dict(),
            "output": str(output_path) if output_path is not None else None,
            "summary_output": str(summary_path) if summary_path is not None else None,
        }

    live_block = _chat_live_model_block(args)
    if live_block is not None:
        return {
            **live_block,
            "benchmark": "finance",
            "message": "Finance benchmark live runs require the model stack. Use --predictions to score existing outputs.",
        }
    live_retrieval = _live_retrieval_config_for_args(args)
    if isinstance(live_retrieval, dict):
        return live_retrieval
    artifact_store = _runtime_artifact_store(args)
    research_corpus_store = _runtime_corpus_store(args)
    items = load_finance_benchmark_items(args.dataset, limit=args.limit, offset=args.offset)
    execution = _execution_profile_for_args(args)
    mission_enabled = _mission_enabled_for_args(args, execution)
    progress_callback = _finance_benchmark_progress_callback(output_path=output_path, total=len(items))
    if int(getattr(args, "parallel", 1) or 1) > 1:
        worker_root = _finance_benchmark_worker_root(args, output_path=output_path)
        results = run_finance_benchmark_parallel(
            items=items,
            runtime_factory=lambda index, item: _finance_benchmark_worker_runtime(
                args,
                live_retrieval=live_retrieval,
                worker_root=worker_root,
                index=index,
                item_id=item.item_id,
            ),
            max_workers=args.parallel,
            thread_prefix=args.thread_prefix,
            question_prefix=args.question_prefix,
            result_callback=progress_callback,
        )
        worker_state_root = str(worker_root)
    else:
        runtime = _chat_runtime(
            journal,
            artifact_store=artifact_store,
            memory_store=_memory_store(args, create_default=True),
            research_corpus_store=research_corpus_store,
            retrieval_operator=_build_live_retrieval_operator(
                live_retrieval,
                artifact_store=artifact_store,
                corpus_store=research_corpus_store,
            )
            if live_retrieval is not None
            else None,
            thread_store=_thread_store(args, create_default=True),
            live_model=_agent_uses_live_model(args),
            model=args.model,
            profile=args.profile,
            thinking=_thinking_override(args.thinking),
            reasoning_effort=args.reasoning_effort,
            max_output_tokens=args.max_output_tokens,
            temperature=args.temperature,
            generation_mode=args.generation_mode,
            latency_target=args.latency_target,
            response_language=_response_language_for_args(args),
            planner_mode=_benchmark_processor_mode(args, "planner", execution),
            evaluator_mode=_benchmark_processor_mode(args, "evaluator", execution),
            synthesizer_mode=_benchmark_processor_mode(args, "synthesizer", execution),
            semantic_mode=_benchmark_processor_mode(args, "semantic_intake", execution),
            turn_router_mode=_benchmark_processor_mode(args, "turn_router", execution),
            default_mode="retrieval",
            execution_metadata=_runtime_execution_metadata(args),
            mission_enabled=mission_enabled,
        )
        results = run_finance_benchmark(
            items=items,
            runtime=runtime,
            thread_prefix=args.thread_prefix,
            question_prefix=args.question_prefix,
            journal=journal,
            result_callback=progress_callback,
        )
        worker_state_root = None
    summary = write_finance_benchmark_outputs(
        results,
        output_path=output_path,
        summary_path=summary_path,
        annotation_path=args.dev_gold,
        journal=journal,
    )
    return {
        "status": "ok",
        "mode": "live_holo",
        "summary": summary.to_dict(),
        "output": str(output_path) if output_path is not None else None,
        "summary_output": str(summary_path) if summary_path is not None else None,
        "parallel": int(getattr(args, "parallel", 1) or 1),
        "worker_state_root": worker_state_root,
        "execution_profile": execution.profile_id if execution is not None else None,
        "mission_enabled": mission_enabled,
    }


def _finance_progress_command(args, journal: JournalStore) -> dict[str, object]:
    task_id = str(getattr(args, "task_id", "") or "").strip() or _finance_progress_latest_task_id(
        journal,
        thread_id=str(getattr(args, "thread_id", "") or "").strip() or None,
        thread_prefix=str(getattr(args, "thread_prefix", "") or "").strip() or None,
    )
    if not task_id:
        return {
            "status": "missing",
            "mode": "finance_progress",
            "reason": "no_matching_task",
            "thread_id": getattr(args, "thread_id", None),
            "thread_prefix": getattr(args, "thread_prefix", None),
        }
    records = journal.records(task_id=task_id)
    if not records:
        return {"status": "missing", "mode": "finance_progress", "reason": "unknown_task", "task_id": task_id}
    latest = records[-1]
    stages = _finance_progress_stages(records)
    open_processor = _finance_progress_open_processor(records)
    latest_error = _finance_progress_latest_error(records)
    return {
        "status": "ok",
        "mode": "finance_progress",
        "task_id": task_id,
        "run_id": latest.run_id,
        "record_count": len(records),
        "latest_record": _finance_progress_record_summary(latest),
        "thread_ids": sorted(_finance_progress_thread_ids(records)),
        "current_stage": _finance_progress_current_stage(stages),
        "open_processor": open_processor,
        "latest_error": latest_error,
        "stages": stages,
        "counters": _finance_progress_counters(records),
        "diagnostics": _finance_progress_diagnostics(records),
        "recent_events": [
            _finance_progress_record_summary(record)
            for record in records[-max(1, int(getattr(args, "limit_events", 24) or 24)) :]
        ],
    }


def _finance_progress_command_from_path(args) -> dict[str, object]:
    path = Path(getattr(args, "journal", default_journal_path()))
    if not path.exists():
        return {"status": "missing", "mode": "finance_progress", "reason": "journal_not_found", "journal": str(path)}
    task_id = str(getattr(args, "task_id", "") or "").strip()
    if not task_id:
        task_id = _finance_progress_latest_task_id_from_path(
            path,
            thread_id=str(getattr(args, "thread_id", "") or "").strip() or None,
            thread_prefix=str(getattr(args, "thread_prefix", "") or "").strip() or None,
        )
    if not task_id:
        return {
            "status": "missing",
            "mode": "finance_progress",
            "reason": "no_matching_task",
            "journal": str(path),
            "thread_id": getattr(args, "thread_id", None),
            "thread_prefix": getattr(args, "thread_prefix", None),
        }
    records = _finance_progress_records_from_path(path, task_id=task_id)
    return _finance_progress_payload_from_records(args, task_id=task_id, records=records)


def _workflow_view_command_from_path(args) -> dict[str, object]:
    path = Path(getattr(args, "journal", default_journal_path()))
    if not path.exists():
        return {"status": "missing", "mode": "workflow_view", "reason": "journal_not_found", "journal": str(path)}
    task_id = str(getattr(args, "task_id", "") or "").strip()
    if not task_id:
        task_id = _finance_progress_latest_task_id_from_path(
            path,
            thread_id=str(getattr(args, "thread_id", "") or "").strip() or None,
            thread_prefix=str(getattr(args, "thread_prefix", "") or "").strip() or None,
        )
    if not task_id:
        return {
            "status": "missing",
            "mode": "workflow_view",
            "reason": "no_matching_task",
            "journal": str(path),
            "thread_id": getattr(args, "thread_id", None),
            "thread_prefix": getattr(args, "thread_prefix", None),
        }
    records = _finance_progress_records_from_path(path, task_id=task_id)
    if not records:
        return {"status": "missing", "mode": "workflow_view", "reason": "unknown_task", "task_id": task_id, "journal": str(path)}
    progress = _finance_progress_payload_from_records(args, task_id=task_id, records=records)
    limit = max(1, int(getattr(args, "limit_events", 240) or 240))
    packets = [_workflow_view_record_packet(record) for record in records[-limit:]]
    groups: dict[str, int] = {}
    for packet in packets:
        group = str(packet.get("group") or "other")
        groups[group] = groups.get(group, 0) + 1
    return {
        "status": "ok",
        "mode": "workflow_view",
        "schema": "holo.kernel_v3.workflow_view.v1",
        "journal": str(path),
        "task_id": task_id,
        "run_id": progress.get("run_id"),
        "thread_ids": progress.get("thread_ids"),
        "record_count": len(records),
        "shown_record_count": len(packets),
        "current_stage": progress.get("current_stage"),
        "stages": progress.get("stages"),
        "counters": progress.get("counters"),
        "diagnostics": progress.get("diagnostics"),
        "open_processor": progress.get("open_processor"),
        "latest_error": progress.get("latest_error"),
        "packet_groups": dict(sorted(groups.items())),
        "packets": packets,
    }


def _workflow_view_record_packet(record: LedgerRecord) -> JsonObject:
    data = record.data if isinstance(record.data, dict) else {}
    group = _workflow_view_group(record.kind, data)
    packet: JsonObject = {
        "record_id": record.record_id,
        "recorded_at_ms": record.recorded_at_ms,
        "kind": record.kind,
        "group": group,
        "run_id": record.run_id,
        "step_id": record.step_id,
        "schema": data.get("schema") if isinstance(data.get("schema"), str) else None,
        "status": data.get("status") or data.get("decision") or data.get("route") or data.get("reason"),
        "processor": data.get("task_type") or data.get("processor"),
        "tool": data.get("name") or data.get("tool") or data.get("source"),
        "summary": _workflow_view_summary(record.kind, data),
        "state_delta": record.state_delta,
        "artifact_refs": list(record.artifact_refs or []),
        "data": _workflow_view_compact_data(record.kind, data),
    }
    return {key: value for key, value in packet.items() if value not in (None, [], {})}


def _workflow_view_group(kind: str, data: JsonObject) -> str:
    processor = str(data.get("task_type") or data.get("processor") or "")
    if kind in {"processor_request", "processor_result"}:
        return "llm"
    if kind in {"compiled_task_program", "retrieval_workbench_decision", "finance_numeric_judge"} or processor in {
        "task.compile",
        "retrieval.workbench",
        "finance.numeric_judge",
    }:
        return "llm_judgment"
    if kind in {"action", "observation"} or kind.startswith("retrieval_") or kind.startswith("toolchain_"):
        return "tool"
    if kind in {"finance_fact_ledger", "claim_ledger", "slot_frame", "transform_plan"}:
        return "substrate"
    if kind in {"finance_numeric_verification", "verifier_gate_result", "synthesis_gate_result"}:
        return "gate"
    if kind in {"agent_final_answer", "agent_failure_report", "chat_agent_result", "finance_benchmark_item_result"}:
        return "final"
    return "state"


def _workflow_view_summary(kind: str, data: JsonObject) -> str:
    if kind in {"processor_request", "processor_result"}:
        return " ".join(
            item
            for item in [
                str(data.get("task_type") or data.get("processor") or "processor"),
                str(data.get("status") or ""),
                str(data.get("error") or ""),
            ]
            if item
        )
    if kind == "retrieval_workbench_decision":
        return f"decision={data.get('decision') or '-'} missing={_compact_progress_list(data.get('missing_slots'))}"
    if kind == "finance_numeric_judge":
        return f"decision={data.get('decision') or data.get('status') or '-'} error={data.get('processor_error') or '-'}"
    if kind == "slot_frame":
        return f"task_type={data.get('task_type') or '-'} missing={_compact_progress_list(data.get('missing_slots'))}"
    if kind == "transform_plan":
        return f"method={data.get('method') or data.get('formula_name') or '-'} status={data.get('status') or '-'}"
    if kind in {"finance_numeric_verification", "verifier_gate_result", "synthesis_gate_result"}:
        diagnostics = data.get("diagnostics") if isinstance(data.get("diagnostics"), dict) else {}
        return f"status={data.get('status') or '-'} gate={data.get('gate_id') or diagnostics.get('gate_id') or '-'}"
    if kind in {"agent_failure_report", "finance_benchmark_item_result"}:
        return f"status={data.get('status') or '-'} reason={data.get('reason') or data.get('failure_reason') or '-'}"
    if kind == "agent_final_answer":
        return _workflow_preview(str(data.get("answer") or ""), 160)
    return _workflow_preview(json.dumps(_workflow_view_compact_data(kind, data), ensure_ascii=False, sort_keys=True), 180)


def _workflow_view_compact_data(kind: str, data: JsonObject) -> JsonObject:
    keep = {
        "schema",
        "task_type",
        "processor",
        "provider",
        "model",
        "status",
        "error",
        "decision",
        "reason",
        "reason_summary",
        "route",
        "action_id",
        "name",
        "source",
        "tool",
        "query",
        "queries",
        "uri",
        "title",
        "citation_refs",
        "used_evidence",
        "missing_evidence",
        "missing_slots",
        "next_queries",
        "next_source_families",
        "next_document_targets",
        "required_slots",
        "filled_slots",
        "method",
        "status",
        "issues",
        "diagnostics",
        "processor_status",
        "processor_error",
        "repair_instruction",
        "requires_more_work",
        "answer_addresses_question",
        "core_numeric_claims",
        "unsupported_core_values",
        "non_core_numeric_claims",
        "candidate_supported_values",
    }
    compact = {key: value for key, value in data.items() if key in keep and value not in (None, [], {})}
    for key in ("answer", "text", "preview", "prompt"):
        value = data.get(key)
        if isinstance(value, str) and value:
            compact[key] = _workflow_preview(value, 1200)
        elif isinstance(value, dict):
            compact[key] = value
    if kind in {"claim_ledger", "finance_fact_ledger"}:
        items = data.get("claims") if isinstance(data.get("claims"), list) else data.get("facts")
        if isinstance(items, list):
            compact["item_count"] = len(items)
            compact["items_preview"] = items[:12]
    return compact


def _render_workflow_view_html(payload: JsonObject) -> str:
    title = f"Holo Workflow View - {payload.get('task_id') or payload.get('status')}"
    data = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    if payload.get("status") != "ok":
        body = f"<pre>{html.escape(json.dumps(payload, ensure_ascii=False, indent=2))}</pre>"
        return _workflow_view_html_shell(title, body, data)
    stages = payload.get("stages") if isinstance(payload.get("stages"), list) else []
    packets = payload.get("packets") if isinstance(payload.get("packets"), list) else []
    counters = payload.get("counters") if isinstance(payload.get("counters"), dict) else {}
    diagnostics = payload.get("diagnostics") if isinstance(payload.get("diagnostics"), dict) else {}
    stage_html = "\n".join(_workflow_stage_card(stage) for stage in stages if isinstance(stage, dict))
    packet_html = "\n".join(_workflow_packet_card(packet) for packet in packets if isinstance(packet, dict))
    body = f"""
<header>
  <div>
    <h1>Holo Workflow View</h1>
    <p class="muted">task={html.escape(str(payload.get('task_id') or '-'))} run={html.escape(str(payload.get('run_id') or '-'))} records={payload.get('record_count')} shown={payload.get('shown_record_count')}</p>
  </div>
  <div class="status">{html.escape(str(payload.get('current_stage') or 'unknown'))}</div>
</header>
<section class="panel">
  <h2>Topology</h2>
  <div class="stages">{stage_html}</div>
</section>
<section class="grid">
  <div class="panel"><h2>Counters</h2><pre>{html.escape(json.dumps(counters, ensure_ascii=False, indent=2))}</pre></div>
  <div class="panel"><h2>Diagnostics</h2><pre>{html.escape(json.dumps(diagnostics, ensure_ascii=False, indent=2))}</pre></div>
</section>
<section class="panel">
  <h2>Packet Timeline</h2>
  <div class="toolbar">
    <input id="filter" placeholder="filter packets by kind/group/status/text" />
    <button data-filter="">All</button>
    <button data-filter="llm">LLM</button>
    <button data-filter="tool">Tools</button>
    <button data-filter="substrate">Substrate</button>
    <button data-filter="gate">Gates</button>
    <button data-filter="final">Final</button>
  </div>
  <div id="packets">{packet_html}</div>
</section>
<script id="workflow-data" type="application/json">{html.escape(data)}</script>
<script>
const filter = document.getElementById('filter');
const cards = Array.from(document.querySelectorAll('.packet'));
function applyFilter(value) {{
  const q = String(value || '').toLowerCase();
  for (const card of cards) {{
    card.style.display = card.dataset.search.includes(q) ? '' : 'none';
  }}
}}
filter.addEventListener('input', () => applyFilter(filter.value));
for (const btn of document.querySelectorAll('button[data-filter]')) {{
  btn.addEventListener('click', () => {{ filter.value = btn.dataset.filter; applyFilter(filter.value); }});
}}
</script>
"""
    return _workflow_view_html_shell(title, body, data)


def _workflow_view_html_shell(title: str, body: str, data: str) -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>{html.escape(title)}</title>
<style>
:root {{ color-scheme: light; --bg:#f7f8fa; --fg:#1d2430; --muted:#667085; --line:#d9dee8; --panel:#ffffff; --llm:#3657d9; --tool:#0f766e; --sub:#7c3aed; --gate:#b45309; --final:#166534; --bad:#b42318; }}
body {{ margin:0; font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, Arial, sans-serif; background:var(--bg); color:var(--fg); }}
header {{ display:flex; align-items:center; justify-content:space-between; gap:16px; padding:22px 28px; border-bottom:1px solid var(--line); background:#fff; position:sticky; top:0; z-index:2; }}
h1 {{ margin:0; font-size:24px; }} h2 {{ margin:0 0 12px; font-size:16px; }} .muted {{ color:var(--muted); margin:4px 0 0; }}
.status {{ padding:8px 12px; border:1px solid var(--line); background:#f2f4f7; border-radius:6px; font-weight:600; }}
.panel {{ margin:18px 28px; padding:16px; background:var(--panel); border:1px solid var(--line); border-radius:8px; }}
.grid {{ display:grid; grid-template-columns: minmax(0,1fr) minmax(0,1fr); gap:0; }}
.stages {{ display:grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap:10px; }}
.stage {{ border:1px solid var(--line); border-left:5px solid #98a2b3; padding:10px; border-radius:8px; min-height:78px; background:#fcfcfd; }}
.stage.done {{ border-left-color:var(--final); }} .stage.current {{ border-left-color:var(--llm); background:#eef4ff; }} .stage.pending {{ opacity:.72; }}
.stage .label {{ font-weight:700; }} .stage .small {{ font-size:12px; color:var(--muted); margin-top:5px; overflow-wrap:anywhere; }}
.toolbar {{ display:flex; gap:8px; margin-bottom:12px; flex-wrap:wrap; }} input {{ min-width:320px; flex:1; padding:10px; border:1px solid var(--line); border-radius:6px; }} button {{ padding:9px 12px; border:1px solid var(--line); border-radius:6px; background:#fff; cursor:pointer; }}
.packet {{ border:1px solid var(--line); border-left:5px solid #98a2b3; border-radius:8px; padding:12px; margin:10px 0; background:#fff; }}
.packet.llm,.packet.llm_judgment {{ border-left-color:var(--llm); }} .packet.tool {{ border-left-color:var(--tool); }} .packet.substrate {{ border-left-color:var(--sub); }} .packet.gate {{ border-left-color:var(--gate); }} .packet.final {{ border-left-color:var(--final); }}
.packet.failed {{ background:#fff7f6; border-left-color:var(--bad); }}
.packet-head {{ display:flex; align-items:baseline; justify-content:space-between; gap:12px; }} .packet-title {{ font-weight:700; overflow-wrap:anywhere; }} .badge {{ font-size:12px; color:#fff; background:#475467; border-radius:999px; padding:3px 8px; }}
.summary {{ margin:8px 0; color:#344054; overflow-wrap:anywhere; }} details {{ margin-top:8px; }} pre {{ white-space:pre-wrap; overflow-wrap:anywhere; background:#f8fafc; border:1px solid #eaecf0; padding:10px; border-radius:6px; max-height:420px; overflow:auto; }}
@media (max-width: 760px) {{ .grid {{ grid-template-columns:1fr; }} header {{ position:static; flex-direction:column; align-items:flex-start; }} input {{ min-width:0; }} }}
</style>
</head>
<body>
{body}
</body>
</html>
"""


def _workflow_stage_card(stage: JsonObject) -> str:
    status = html.escape(str(stage.get("status") or "pending"))
    latest = stage.get("latest") if isinstance(stage.get("latest"), dict) else {}
    latest_text = " ".join(
        str(item)
        for item in [
            latest.get("kind"),
            latest.get("status"),
            latest.get("processor"),
            latest.get("error"),
        ]
        if item
    )
    return (
        f'<div class="stage {status}">'
        f'<div class="label">{html.escape(str(stage.get("label") or stage.get("stage") or "-"))}</div>'
        f'<div class="small">status={status} count={html.escape(str(stage.get("count") or 0))}</div>'
        f'<div class="small">{html.escape(_workflow_preview(latest_text, 180))}</div>'
        "</div>"
    )


def _workflow_preview(value: object, limit: int) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)] + "…"


def _workflow_packet_card(packet: JsonObject) -> str:
    group = str(packet.get("group") or "state")
    status = str(packet.get("status") or "")
    failed = " failed" if status.lower() in {"failed", "error", "blocked"} or packet.get("data", {}).get("error") else ""
    search = html.escape(json.dumps(packet, ensure_ascii=False, sort_keys=True).lower())
    title = f"{packet.get('record_id')} | {packet.get('kind')}"
    details = json.dumps(packet.get("data") or {}, ensure_ascii=False, sort_keys=True, indent=2)
    return f"""
<article class="packet {html.escape(group)}{failed}" data-search="{search}">
  <div class="packet-head">
    <div class="packet-title">{html.escape(title)}</div>
    <span class="badge">{html.escape(group)}</span>
  </div>
  <div class="summary">{html.escape(str(packet.get('summary') or ''))}</div>
  <div class="muted">schema={html.escape(str(packet.get('schema') or '-'))} status={html.escape(status or '-')} processor={html.escape(str(packet.get('processor') or '-'))} tool={html.escape(str(packet.get('tool') or '-'))}</div>
  <details><summary>packet JSON</summary><pre>{html.escape(details)}</pre></details>
</article>
"""


def _finance_progress_latest_task_id_from_path(
    path: Path,
    *,
    thread_id: str | None,
    thread_prefix: str | None,
) -> str | None:
    latest: str | None = None
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if thread_id and thread_id not in line:
                continue
            if thread_prefix and thread_prefix not in line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            task_id = payload.get("task_id")
            if not isinstance(task_id, str) or not task_id:
                continue
            if thread_id or thread_prefix:
                data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
                thread_ids: set[str] = set()
                _collect_thread_ids(data, thread_ids, depth=0)
                if thread_id and thread_id not in thread_ids:
                    continue
                if thread_prefix and not any(item.startswith(thread_prefix) for item in thread_ids):
                    continue
            latest = task_id
    return latest


def _finance_progress_records_from_path(path: Path, *, task_id: str) -> list[LedgerRecord]:
    records: list[LedgerRecord] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if task_id not in line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if payload.get("task_id") != task_id:
                continue
            record = _ledger_record_from_loose_payload(payload)
            if record is not None:
                records.append(record)
    return records


def _ledger_record_from_loose_payload(payload: JsonObject) -> LedgerRecord | None:
    required = {
        "schema_version",
        "record_id",
        "task_id",
        "run_id",
        "step_id",
        "kind",
        "data",
        "recorded_at_ms",
        "event_ref",
        "action_ref",
        "observation_ref",
        "feedback_ref",
        "state_delta",
        "artifact_refs",
        "payload_hash",
    }
    if not required.issubset(payload):
        return None
    filtered = {key: payload.get(key) for key in required}
    return LedgerRecord.from_dict(filtered)


def _finance_progress_payload_from_records(args, *, task_id: str, records: list[LedgerRecord]) -> dict[str, object]:
    if not records:
        return {"status": "missing", "mode": "finance_progress", "reason": "unknown_task", "task_id": task_id}
    latest = records[-1]
    stages = _finance_progress_stages(records)
    open_processor = _finance_progress_open_processor(records)
    latest_error = _finance_progress_latest_error(records)
    return {
        "status": "ok",
        "mode": "finance_progress",
        "task_id": task_id,
        "run_id": latest.run_id,
        "record_count": len(records),
        "latest_record": _finance_progress_record_summary(latest),
        "thread_ids": sorted(_finance_progress_thread_ids(records)),
        "current_stage": _finance_progress_current_stage(stages),
        "open_processor": open_processor,
        "latest_error": latest_error,
        "stages": stages,
        "counters": _finance_progress_counters(records),
        "diagnostics": _finance_progress_diagnostics(records),
        "recent_events": [
            _finance_progress_record_summary(record)
            for record in records[-max(1, int(getattr(args, "limit_events", 24) or 24)) :]
        ],
    }


def _finance_progress_latest_task_id(
    journal: JournalStore,
    *,
    thread_id: str | None,
    thread_prefix: str | None,
) -> str | None:
    for record in reversed(journal.records()):
        task_id = record.task_id
        if not task_id:
            continue
        if thread_id or thread_prefix:
            thread_ids = _finance_progress_thread_ids([record])
            if thread_id and thread_id not in thread_ids:
                continue
            if thread_prefix and not any(item.startswith(thread_prefix) for item in thread_ids):
                continue
        return task_id
    return None


def _finance_progress_thread_ids(records: list[object]) -> set[str]:
    values: set[str] = set()
    for record in records:
        data = getattr(record, "data", {})
        _collect_thread_ids(data, values, depth=0)
    return values


def _collect_thread_ids(value: object, values: set[str], *, depth: int) -> None:
    if depth > 4:
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "thread_id" and isinstance(item, str) and item:
                values.add(item)
            elif isinstance(item, (dict, list)):
                _collect_thread_ids(item, values, depth=depth + 1)
    elif isinstance(value, list):
        for item in value[:32]:
            if isinstance(item, (dict, list)):
                _collect_thread_ids(item, values, depth=depth + 1)


def _finance_progress_stages(records: list[object]) -> list[JsonObject]:
    definitions = [
        ("task", "Task intake", {"task", "chat_turn", "chat_route"}, (), ()),
        (
            "semantic_recipe",
            "Semantic / recipe",
            {"semantic_intake", "semantic_goal", "semantic_task_graph", "semantic_task_plan", "agent_recipe"},
            (),
            ("semantic.intake", "chat.route"),
        ),
        ("task_compile", "Task compiler", {"compiled_task_program"}, (), ("task.compile",)),
        ("planner", "Planner", {"action", "policy_decision"}, (), ("planner.propose",)),
        ("retrieval", "Retrieval acquisition", set(), ("retrieval_",), ()),
        ("workbench", "LLM evidence workbench", {"retrieval_workbench_decision"}, (), ("retrieval.workbench",)),
        (
            "toolchain",
            "Composable toolchain",
            {
                "toolchain_plan",
                "toolchain_step_proposed",
                "toolchain_step_executed",
                "toolchain_artifact",
                "toolchain_grounding_candidate",
                "toolchain_failure",
            },
            ("toolchain_",),
            (),
        ),
        ("claims", "Facts / claims / slots", {"finance_fact_ledger", "claim_ledger", "slot_frame"}, (), ()),
        ("transforms", "Transforms / calculator", {"transform_plan", "calculator_result"}, (), ()),
        (
            "verification",
            "Verifier / synthesis gate",
            {"finance_numeric_verification", "verifier_gate_result", "synthesis_gate_result"},
            (),
            (),
        ),
        ("final", "Final result", {"agent_final_answer", "agent_failure_report", "chat_agent_result"}, (), ("synthesizer.answer",)),
    ]
    stages: list[JsonObject] = []
    for stage_id, label, kinds, prefixes, processors in definitions:
        matched = [record for record in records if _finance_progress_record_matches(record, kinds, prefixes, processors)]
        latest = matched[-1] if matched else None
        stages.append(
            {
                "stage": stage_id,
                "label": label,
                "present": bool(matched),
                "count": len(matched),
                "latest": _finance_progress_record_summary(latest) if latest is not None else None,
            }
        )
    current = _finance_progress_current_stage(stages)
    seen_current = False
    for stage in stages:
        if stage["stage"] == current:
            seen_current = True
            stage["status"] = "current" if current != "final" else "done"
        elif stage.get("present"):
            stage["status"] = "done"
        elif not seen_current:
            stage["status"] = "pending"
        else:
            stage["status"] = "pending"
    return stages


def _finance_progress_record_matches(
    record: object,
    kinds: set[str],
    prefixes: tuple[str, ...],
    processors: tuple[str, ...],
) -> bool:
    kind = str(getattr(record, "kind", "") or "")
    if kind in kinds or any(kind.startswith(prefix) for prefix in prefixes):
        return True
    if kind in {"processor_request", "processor_result"}:
        data = getattr(record, "data", {})
        processor = str(data.get("processor") or data.get("task_type") or "")
        if any(processor == item or processor.startswith(item) for item in processors):
            return True
    return False


def _finance_progress_current_stage(stages: list[JsonObject]) -> str | None:
    for stage in reversed(stages):
        if stage.get("present"):
            return str(stage.get("stage") or "")
    return None


def _finance_progress_open_processor(records: list[object]) -> JsonObject | None:
    requests: dict[str, object] = {}
    results: set[str] = set()
    for record in records:
        data = getattr(record, "data", {})
        if getattr(record, "kind", "") == "processor_request":
            request_id = str(data.get("request_id") or "")
            if request_id:
                requests[request_id] = record
        elif getattr(record, "kind", "") == "processor_result":
            request_id = str(data.get("request_id") or "")
            if request_id:
                results.add(request_id)
    for request_id, record in reversed(list(requests.items())):
        if request_id not in results:
            summary = _finance_progress_record_summary(record)
            summary["request_id"] = request_id
            return summary
    return None


def _finance_progress_latest_error(records: list[object]) -> JsonObject | None:
    failure_kinds = {
        "agent_failure_report",
        "toolchain_failure",
        "retrieval_failure_attribution",
        "retrieval_source_rejections",
    }
    for record in reversed(records):
        data = getattr(record, "data", {})
        kind = str(getattr(record, "kind", "") or "")
        status = str(data.get("status") or "").strip().lower()
        if kind == "finance_benchmark_item_result" and status in {"passed", "ok"}:
            return None
        error = data.get("error") or data.get("failure_reason")
        if error or status in {"failed", "blocked", "error"} or kind in failure_kinds:
            return _finance_progress_record_summary(record)
    return None


def _finance_progress_counters(records: list[object]) -> JsonObject:
    kinds: dict[str, int] = {}
    processor_errors = 0
    for record in records:
        kind = str(getattr(record, "kind", "") or "")
        kinds[kind] = kinds.get(kind, 0) + 1
        if kind == "processor_result":
            data = getattr(record, "data", {})
            if data.get("status") == "failed" or data.get("error"):
                processor_errors += 1
    return {
        "processor_calls": kinds.get("processor_result", 0),
        "processor_errors": processor_errors,
        "retrieval_reports": kinds.get("retrieval_report", 0),
        "fetch_attempts": kinds.get("retrieval_fetch_attempt", 0),
        "extractions": kinds.get("retrieval_extraction", 0),
        "workbench_decisions": kinds.get("retrieval_workbench_decision", 0),
        "claim_ledgers": kinds.get("claim_ledger", 0),
        "slot_frames": kinds.get("slot_frame", 0),
        "transform_plans": kinds.get("transform_plan", 0),
        "calculator_results": kinds.get("calculator_result", 0),
        "verifier_gates": kinds.get("verifier_gate_result", 0),
        "synthesis_gates": kinds.get("synthesis_gate_result", 0),
        "toolchain_steps": kinds.get("toolchain_step_executed", 0),
        "by_kind": dict(sorted(kinds.items())),
    }


def _finance_progress_diagnostics(records: list[object]) -> JsonObject:
    latest_by_kind: dict[str, JsonObject] = {}
    reader_parser_counts: dict[str, int] = {}
    reader_latest: JsonObject = {}
    target_span_count = 0
    for record in records:
        kind = str(getattr(record, "kind", "") or "")
        data = getattr(record, "data", {})
        if isinstance(data, dict):
            latest_by_kind[kind] = data
        if kind != "retrieval_extraction" or not isinstance(data, dict):
            continue
        diagnostics = data.get("diagnostics") if isinstance(data.get("diagnostics"), dict) else {}
        reader = diagnostics.get("document_reader") if isinstance(diagnostics.get("document_reader"), dict) else {}
        parser = str(reader.get("parser_used") or reader.get("parser_library") or "")
        if parser:
            reader_parser_counts[parser] = reader_parser_counts.get(parser, 0) + 1
            reader_latest = {
                "parser_used": parser,
                "chars_extracted": reader.get("chars_extracted"),
                "pages_extracted": reader.get("pages_extracted"),
                "table_like_blocks": reader.get("table_like_blocks"),
                "readable_text_limit": reader.get("readable_text_limit"),
            }
        spans = data.get("spans") if isinstance(data.get("spans"), list) else []
        for span in spans:
            if isinstance(span, dict):
                metadata = span.get("metadata") if isinstance(span.get("metadata"), dict) else {}
                if metadata.get("target_slot") or metadata.get("target_line_item"):
                    target_span_count += 1
    fact_metrics: dict[str, int] = {}
    fact_sources: dict[str, int] = {}
    fact_ledger = latest_by_kind.get("finance_fact_ledger") or {}
    facts = fact_ledger.get("facts") if isinstance(fact_ledger.get("facts"), list) else []
    for fact in facts:
        if not isinstance(fact, dict):
            continue
        metric = str(fact.get("metric") or "")
        if metric:
            fact_metrics[metric] = fact_metrics.get(metric, 0) + 1
        metadata = fact.get("metadata") if isinstance(fact.get("metadata"), dict) else {}
        source = str(metadata.get("source") or "")
        if source:
            fact_sources[source] = fact_sources.get(source, 0) + 1
    slot_frame = latest_by_kind.get("slot_frame") or {}
    formula_plan = latest_by_kind.get("finance_formula_plan") or {}
    workbench = latest_by_kind.get("retrieval_workbench_decision") or {}
    benchmark = latest_by_kind.get("finance_benchmark_item_result") or {}
    benchmark_scorecard = benchmark.get("scorecard") if isinstance(benchmark.get("scorecard"), dict) else {}
    return {
        "document_reader": {
            "parser_counts": dict(sorted(reader_parser_counts.items())),
            "latest": {key: value for key, value in reader_latest.items() if value is not None},
            "target_span_count": target_span_count,
        },
        "workbench": {
            "decision": workbench.get("decision"),
            "rescued_count": workbench.get("rescued_count"),
            "missing_slots": workbench.get("missing_slots"),
            "next_queries": workbench.get("next_queries"),
            "next_source_families": workbench.get("next_source_families"),
            "reason_summary": workbench.get("reason_summary"),
        },
        "slot_frame": {
            "task_type": slot_frame.get("task_type"),
            "missing_slots": slot_frame.get("missing_slots"),
        },
        "formula_plan": {
            "status": formula_plan.get("status"),
            "formula_name": formula_plan.get("formula_name"),
            "missing_facts": formula_plan.get("missing_facts"),
            "source": formula_plan.get("source"),
        },
        "fact_ledger": {
            "fact_count": len(facts),
            "top_metrics": _top_counts(fact_metrics, limit=8),
            "top_sources": _top_counts(fact_sources, limit=6),
        },
        "benchmark": {
            "status": benchmark.get("status"),
            "reason": benchmark.get("reason") or benchmark_scorecard.get("reason"),
            "item_id": benchmark.get("item_id"),
        },
    }


def _top_counts(counts: dict[str, int], *, limit: int) -> list[JsonObject]:
    return [
        {"name": key, "count": value}
        for key, value in sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:limit]
    ]


def _finance_progress_record_summary(record: object | None) -> JsonObject | None:
    if record is None:
        return None
    data = getattr(record, "data", {})
    kind = str(getattr(record, "kind", "") or "")
    summary: JsonObject = {
        "record_id": getattr(record, "record_id", None),
        "kind": kind,
        "run_id": getattr(record, "run_id", None),
        "step_id": getattr(record, "step_id", None),
    }
    if kind in {"processor_request", "processor_result"}:
        prompt = data.get("prompt") if isinstance(data.get("prompt"), dict) else {}
        summary.update(
            {
                "processor": data.get("processor") or data.get("task_type"),
                "status": data.get("status"),
                "error": data.get("error"),
                "provider": data.get("provider"),
                "model": data.get("model"),
                "prompt_chars": prompt.get("chars") if isinstance(prompt, dict) else None,
                "duration_ms": data.get("duration_ms"),
            }
        )
    elif kind == "retrieval_fetch_attempt":
        summary.update({"status": data.get("status"), "uri": data.get("uri"), "size_bytes": data.get("size_bytes")})
    elif kind == "retrieval_extraction":
        spans = data.get("spans")
        summary.update({"document_id": _nested_value(data, "document", "document_id"), "spans": len(spans) if isinstance(spans, list) else None})
    elif kind == "retrieval_report":
        diagnostics = data.get("diagnostics") if isinstance(data.get("diagnostics"), dict) else {}
        summary.update(
            {
                "status": data.get("status"),
                "evidence_count": diagnostics.get("evidence_count"),
                "citation_count": diagnostics.get("citation_count"),
            }
        )
    elif kind == "retrieval_workbench_decision":
        summary.update(
            {
                "decision": data.get("decision"),
                "rescued_count": data.get("rescued_count"),
                "missing_slots": data.get("missing_slots"),
                "next_queries": data.get("next_queries"),
            }
        )
    elif kind in {"claim_ledger", "finance_fact_ledger"}:
        claims = data.get("claims") or data.get("facts")
        summary.update({"count": len(claims) if isinstance(claims, list) else data.get("count")})
    elif kind == "slot_frame":
        summary.update({"missing_slots": data.get("missing_slots"), "task_type": data.get("task_type")})
    elif kind == "transform_plan":
        plans = data.get("plans") or data.get("transform_plans")
        summary.update({"count": len(plans) if isinstance(plans, list) else data.get("count")})
    elif kind in {"calculator_result", "finance_numeric_verification", "verifier_gate_result", "synthesis_gate_result"}:
        summary.update({"status": data.get("status"), "reason": data.get("reason") or data.get("failure_reason")})
    elif kind in {"agent_final_answer", "agent_failure_report"}:
        summary.update({"status": data.get("status"), "reason": data.get("reason") or data.get("failure_reason")})
    elif kind == "finance_benchmark_item_result":
        scorecard = data.get("scorecard") if isinstance(data.get("scorecard"), dict) else {}
        summary.update({"status": data.get("status"), "reason": data.get("reason") or scorecard.get("reason")})
    else:
        for key in ("status", "reason", "name", "source", "tool", "action_id", "observation_id"):
            if data.get(key) is not None:
                summary[key] = data.get(key)
    return {key: value for key, value in summary.items() if value is not None}


def _nested_value(data: JsonObject, *keys: str) -> object | None:
    current: object = data
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _render_finance_progress(payload: JsonObject) -> str:
    if payload.get("status") != "ok":
        return json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2)
    lines = [
        "Finance workflow progress",
        f"task={payload.get('task_id')} run={payload.get('run_id')} records={payload.get('record_count')} current={payload.get('current_stage') or '-'}",
    ]
    thread_ids = payload.get("thread_ids")
    if isinstance(thread_ids, list) and thread_ids:
        lines.append("threads=" + ", ".join(str(item) for item in thread_ids[:4]))
    open_processor = payload.get("open_processor")
    if isinstance(open_processor, dict):
        lines.append(
            "open_processor="
            + f"{open_processor.get('processor') or '-'} prompt_chars={open_processor.get('prompt_chars') or '-'} "
            + f"record={open_processor.get('record_id') or '-'}"
        )
    latest_error = payload.get("latest_error")
    if isinstance(latest_error, dict):
        lines.append(
            "latest_error="
            + f"{latest_error.get('kind') or '-'} status={latest_error.get('status') or '-'} "
            + f"error={latest_error.get('error') or latest_error.get('reason') or '-'} record={latest_error.get('record_id') or '-'}"
        )
    lines.append("stages:")
    for stage in payload.get("stages", []):
        if not isinstance(stage, dict):
            continue
        marker = {"done": "ok", "current": "now", "pending": ".."}.get(str(stage.get("status")), "..")
        latest = stage.get("latest") if isinstance(stage.get("latest"), dict) else {}
        latest_text = ""
        if latest:
            latest_text = f" latest={latest.get('kind')}#{latest.get('record_id')}"
            if latest.get("status"):
                latest_text += f" status={latest.get('status')}"
            if latest.get("processor"):
                latest_text += f" processor={latest.get('processor')}"
            if latest.get("prompt_chars"):
                latest_text += f" prompt_chars={latest.get('prompt_chars')}"
        lines.append(f"  [{marker}] {stage.get('label')} count={stage.get('count')}{latest_text}")
    diagnostics = payload.get("diagnostics") if isinstance(payload.get("diagnostics"), dict) else {}
    if diagnostics:
        lines.append("diagnostics:")
        reader = diagnostics.get("document_reader") if isinstance(diagnostics.get("document_reader"), dict) else {}
        if reader:
            latest_reader = reader.get("latest") if isinstance(reader.get("latest"), dict) else {}
            lines.append(
                "  reader="
                + f"target_spans={reader.get('target_span_count') or 0} "
                + f"parsers={_compact_progress_dict_counts(reader.get('parser_counts'))} "
                + f"latest_parser={latest_reader.get('parser_used') or '-'} "
                + f"chars={latest_reader.get('chars_extracted') or '-'} "
                + f"pages={latest_reader.get('pages_extracted') or '-'}"
            )
        slot_frame = diagnostics.get("slot_frame") if isinstance(diagnostics.get("slot_frame"), dict) else {}
        if slot_frame:
            lines.append(
                "  slots="
                + f"task_type={slot_frame.get('task_type') or '-'} "
                + f"missing={_compact_progress_list(slot_frame.get('missing_slots'))}"
            )
        formula_plan = diagnostics.get("formula_plan") if isinstance(diagnostics.get("formula_plan"), dict) else {}
        if formula_plan:
            lines.append(
                "  formula="
                + f"status={formula_plan.get('status') or '-'} "
                + f"name={formula_plan.get('formula_name') or '-'} "
                + f"missing={_compact_progress_list(formula_plan.get('missing_facts'))}"
            )
        facts = diagnostics.get("fact_ledger") if isinstance(diagnostics.get("fact_ledger"), dict) else {}
        if facts:
            lines.append(
                "  facts="
                + f"count={facts.get('fact_count') or 0} "
                + f"metrics={_compact_progress_counts(facts.get('top_metrics'))} "
                + f"sources={_compact_progress_counts(facts.get('top_sources'))}"
            )
        workbench = diagnostics.get("workbench") if isinstance(diagnostics.get("workbench"), dict) else {}
        if workbench:
            lines.append(
                "  workbench="
                + f"decision={workbench.get('decision') or '-'} "
                + f"missing={_compact_progress_list(workbench.get('missing_slots'))} "
                + f"next_queries={_compact_progress_list(workbench.get('next_queries'))}"
            )
        benchmark = diagnostics.get("benchmark") if isinstance(diagnostics.get("benchmark"), dict) else {}
        if benchmark and (benchmark.get("status") or benchmark.get("reason")):
            lines.append(
                "  benchmark="
                + f"status={benchmark.get('status') or '-'} reason={benchmark.get('reason') or '-'}"
            )
    counters = payload.get("counters") if isinstance(payload.get("counters"), dict) else {}
    lines.append(
        "counters: "
        + " ".join(
            f"{key}={counters.get(key)}"
            for key in (
                "processor_calls",
                "processor_errors",
                "retrieval_reports",
                "fetch_attempts",
                "extractions",
                "workbench_decisions",
                "claim_ledgers",
                "slot_frames",
                "transform_plans",
                "calculator_results",
                "verifier_gates",
                "synthesis_gates",
                "toolchain_steps",
            )
        )
    )
    lines.append("recent:")
    for event in payload.get("recent_events", []):
        if not isinstance(event, dict):
            continue
        details = []
        for key in ("processor", "status", "error", "decision", "uri", "prompt_chars", "duration_ms", "count"):
            if event.get(key) is not None:
                details.append(f"{key}={event.get(key)}")
        lines.append(f"  {event.get('record_id')} {event.get('kind')} " + " ".join(details))
    return "\n".join(lines)


def _compact_progress_list(value: object, *, limit: int = 4) -> str:
    if not isinstance(value, list) or not value:
        return "-"
    items = [str(item) for item in value[:limit]]
    if len(value) > limit:
        items.append(f"+{len(value) - limit}")
    return ",".join(items)


def _compact_progress_counts(value: object, *, limit: int = 5) -> str:
    if not isinstance(value, list) or not value:
        return "-"
    parts: list[str] = []
    for item in value[:limit]:
        if isinstance(item, dict):
            parts.append(f"{item.get('name') or '-'}:{item.get('count') or 0}")
    if len(value) > limit:
        parts.append(f"+{len(value) - limit}")
    return ",".join(parts) if parts else "-"


def _compact_progress_dict_counts(value: object, *, limit: int = 5) -> str:
    if not isinstance(value, dict) or not value:
        return "-"
    parts = [
        f"{key}:{count}"
        for key, count in sorted(value.items(), key=lambda item: (-int(item[1] or 0), str(item[0])))[:limit]
    ]
    if len(value) > limit:
        parts.append(f"+{len(value) - limit}")
    return ",".join(parts)


def _finance_benchmark_progress_callback(
    *,
    output_path: Path | None,
    total: int,
) -> Callable[[int, FinanceBenchmarkItem, FinanceBenchmarkResult], None] | None:
    if total <= 0:
        return None
    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text("", encoding="utf-8")

    completed = 0

    def on_result(index: int, item: FinanceBenchmarkItem, result: FinanceBenchmarkResult) -> None:
        nonlocal completed
        completed += 1
        if output_path is not None:
            with output_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(result.to_dict(), ensure_ascii=False, sort_keys=True) + "\n")
        metrics = result.trace_metrics or {}
        tokens = metrics.get("total_tokens")
        retrieval_runs = metrics.get("retrieval_run_count")
        fetches = metrics.get("fetch_attempt_count")
        downloaded_bytes = metrics.get("downloaded_bytes")
        cache_hits = metrics.get("cache_hit_count")
        budget_blocks = metrics.get("download_budget_block_count")
        duration_ms = metrics.get("processor_duration_ms")
        calculator_calls = metrics.get("calculator_call_count")
        formula_traces = metrics.get("formula_trace_count")
        finance_facts = metrics.get("finance_fact_count")
        claim_count = metrics.get("claim_count")
        missing_slots = metrics.get("missing_slot_count")
        transform_plans = metrics.get("transform_plan_count")
        verifier_gate = metrics.get("verifier_gate_status")
        synthesis_gate = metrics.get("synthesis_gate_status")
        synthesis_repaired = metrics.get("synthesis_gate_repaired")
        verifier_status = metrics.get("numeric_verifier_status")
        support_rate = metrics.get("answer_numeric_support_rate")
        numeric_failure = metrics.get("finance_numeric_failure_reason")
        reason = result.scorecard.get("reason") if isinstance(result.scorecard, dict) else None
        print(
            "[bench] "
            f"{completed}/{total} item={item.item_id} index={index} status={result.status} "
            f"reason={reason or '-'} tokens={tokens if tokens is not None else '-'} "
            f"fetches={fetches if fetches is not None else '-'} "
            f"download_mb={_mb(downloaded_bytes) if downloaded_bytes is not None else '-'} "
            f"cache_hits={cache_hits if cache_hits is not None else '-'} "
            f"budget_blocks={budget_blocks if budget_blocks is not None else '-'} "
            f"retrieval_runs={retrieval_runs if retrieval_runs is not None else '-'} "
            f"calc={calculator_calls if calculator_calls is not None else '-'} "
            f"formula={formula_traces if formula_traces is not None else '-'} "
            f"facts={finance_facts if finance_facts is not None else '-'} "
            f"claims={claim_count if claim_count is not None else '-'} "
            f"slots_missing={missing_slots if missing_slots is not None else '-'} "
            f"transforms={transform_plans if transform_plans is not None else '-'} "
            f"verifier={verifier_status or '-'} "
            f"gate={verifier_gate or '-'} "
            f"synth_gate={synthesis_gate or '-'} "
            f"synth_repair={synthesis_repaired if synthesis_repaired is not None else '-'} "
            f"num_support={_percent_for_progress(support_rate)} "
            f"num_fail={numeric_failure or '-'} "
            f"processor_ms={duration_ms if duration_ms is not None else '-'}",
            file=sys.stderr,
            flush=True,
        )

    return on_result


def _percent_for_progress(value: object) -> str:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return "-"
    return f"{value * 100:.1f}%"


def _mb(value: object) -> str:
    try:
        parsed = int(value or 0)
    except (TypeError, ValueError):
        return "-"
    return f"{parsed / 1_000_000:.1f}"


def _finance_benchmark_worker_root(args, *, output_path: Path | None) -> Path:
    configured = getattr(args, "worker_state_root", None)
    if configured:
        return Path(configured)
    if output_path is not None:
        base = output_path.parent / f"{output_path.stem}.workers"
    else:
        base = Path(".state/kernel_v3/bench/finance/workers")
    return base / finance_benchmark_run_id()


def _finance_benchmark_worker_runtime(
    args,
    *,
    live_retrieval: LiveRetrievalConfig | None,
    worker_root: Path,
    index: int,
    item_id: str,
) -> ChatRuntime:
    execution = _execution_profile_for_args(args)
    item_root = worker_root / f"{index:04d}-{safe_storage_id(item_id)}"
    journal = JournalStore(item_root / "journal.jsonl", index_path=item_root / "journal.sqlite")
    artifact_store = ArtifactStore(item_root / "artifacts.jsonl")
    corpus_store = ResearchCorpusStore(item_root / "corpus.jsonl", index_path=item_root / "corpus.sqlite")
    memory_store = MemoryStore(item_root / "memory.jsonl", index_path=item_root / "memory.sqlite")
    return _chat_runtime(
        journal,
        artifact_store=artifact_store,
        memory_store=memory_store,
        research_corpus_store=corpus_store,
        retrieval_operator=_build_live_retrieval_operator(
            live_retrieval,
            artifact_store=artifact_store,
            corpus_store=corpus_store,
        )
        if live_retrieval is not None
        else None,
        thread_store=ThreadTranscriptStore(item_root / "threads"),
        live_model=_agent_uses_live_model(args),
        model=args.model,
        profile=args.profile,
        thinking=_thinking_override(args.thinking),
        reasoning_effort=args.reasoning_effort,
        max_output_tokens=args.max_output_tokens,
        temperature=args.temperature,
        generation_mode=args.generation_mode,
        latency_target=args.latency_target,
        response_language=_response_language_for_args(args),
        planner_mode=_benchmark_processor_mode(args, "planner", execution),
        evaluator_mode=_benchmark_processor_mode(args, "evaluator", execution),
        synthesizer_mode=_benchmark_processor_mode(args, "synthesizer", execution),
        semantic_mode=_benchmark_processor_mode(args, "semantic_intake", execution),
        turn_router_mode=_benchmark_processor_mode(args, "turn_router", execution),
        default_mode="retrieval",
        execution_metadata=_runtime_execution_metadata(args),
        mission_enabled=_mission_enabled_for_args(args, execution),
    )


def _resident_command(args, journal: JournalStore) -> dict[str, object]:
    queue = _resident_queue(args)
    command = args.resident_command
    if command == "enqueue":
        message = queue.enqueue(
            thread_id=args.thread,
            text=args.text,
            source="cli",
            priority=args.priority,
            message_id=args.message_id,
        )
        journal.append(
            task_id=None,
            run_id="resident-cli",
            step_id=None,
            kind="resident_inbox_enqueued",
            data=resident_inbox_event(message),
            state_delta={"resident_inbox_status": message.status, "resident_message_id": message.message_id},
        )
        return {"status": "ok", "message": message.to_dict()}
    if command == "inbox":
        return {"status": "ok", "messages": [message.to_dict() for message in queue.inbox_messages()]}
    if command == "outbox":
        return {"status": "ok", "messages": [message.to_dict() for message in queue.outbox_messages()]}
    if command == "status":
        scheduler = ResidentScheduler(queue=queue, journal=journal)
        return {"status": "ok", "queue": queue.status().to_dict(), "schedules": scheduler.status().to_dict()}
    if command == "inspect":
        inspection = queue.inspect(sample_limit=args.sample_limit)
        scheduler = ResidentScheduler(queue=queue, journal=journal)
        schedule_inspection = scheduler.inspect(sample_limit=args.sample_limit)
        status = _combined_health(inspection.status, schedule_inspection.status)
        return {
            "status": status,
            "inspection": inspection.to_dict(),
            "schedule_inspection": schedule_inspection.to_dict(),
        }
    if command == "doctor":
        scheduler = ResidentScheduler(queue=queue, journal=journal)
        memory_store = _memory_store(args, create_default=_memory_configured(args))
        corpus_store = _corpus_store(args, create_default=_corpus_configured(args))
        artifact_store = _artifact_store(args, create_default=False)
        live_retrieval = _live_retrieval_doctor_config(args)
        live_operator = live_retrieval["operator"]
        report = ResidentDoctor(
            queue=queue,
            scheduler=scheduler,
            journal=journal,
            artifact_store=artifact_store,
            memory_store=memory_store,
            corpus_store=corpus_store,
            retrieval_operator=live_operator
            or _inspectable_retrieval_operator(
                artifact_store=artifact_store or ArtifactStore.in_memory(),
                corpus_store=corpus_store,
            ),
            research_profile_id=args.research_profile,
        ).inspect(sample_limit=args.sample_limit)
        live_status = _live_retrieval_doctor_status(live_retrieval["issues"])
        status = _combined_health(report.status, live_status)
        journal.append(
            task_id=None,
            run_id="resident-cli",
            step_id=None,
            kind="resident_doctor_report",
            data=resident_doctor_event(
                report,
                overall_status=status,
                live_retrieval_status=live_status if live_retrieval["requested"] else None,
                live_retrieval_issues=live_retrieval["issues"] if live_retrieval["requested"] else None,
                live_retrieval_config=live_retrieval["config"] if live_retrieval["requested"] else None,
            ),
            state_delta={"resident_doctor_status": status},
        )
        return {
            "status": status,
            "doctor": report.to_dict(),
            **(
                {
                    "live_retrieval_config": live_retrieval["config"],
                    "live_retrieval_issues": live_retrieval["issues"],
                }
                if live_retrieval["requested"]
                else {}
            ),
        }
    if command == "schedule-add":
        scheduler = ResidentScheduler(queue=queue, journal=journal)
        schedule = scheduler.add_schedule(
            thread_id=args.thread,
            text=args.text,
            schedule_id=args.schedule_id,
            due_at_ms=args.due_at_ms,
            due_in_ms=args.due_in_ms,
            interval_ms=args.interval_ms,
            max_runs=None if args.unbounded else args.max_runs,
            priority=args.priority,
        )
        return {"status": "ok", "schedule": schedule.to_dict()}
    if command == "schedule-list":
        scheduler = ResidentScheduler(queue=queue, journal=journal)
        schedules = scheduler.list_schedules(include_inactive=args.include_inactive)
        return {
            "status": "ok",
            "schedules": [schedule.to_dict() for schedule in schedules],
        }
    if command == "schedule-tick":
        scheduler = ResidentScheduler(queue=queue, journal=journal)
        return {"status": "ok", "tick": scheduler.tick(limit=args.limit).to_dict()}
    if command == "schedule-disable":
        scheduler = ResidentScheduler(queue=queue, journal=journal)
        schedule = scheduler.disable_schedule(args.schedule_id, reason=args.reason)
        if schedule is None:
            return {"status": "failed", "reason": "schedule_not_found", "schedule_id": args.schedule_id}
        return {"status": "ok", "schedule": schedule.to_dict()}
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
            data=resident_inbox_event(message),
            state_delta={"resident_inbox_status": message.status, "resident_message_id": message.message_id},
        )
        return {"status": "ok", "message": message.to_dict()}
    if command == "cancel":
        message = queue.cancel(args.message_id, reason=args.reason)
        if message is None:
            return {"status": "failed", "reason": "inbox_not_cancelable_or_missing", "message_id": args.message_id}
        journal.append(
            task_id=None,
            run_id="resident-cli",
            step_id=None,
            kind="resident_inbox_canceled",
            data=resident_inbox_event(message),
            state_delta={"resident_inbox_status": message.status, "resident_message_id": message.message_id},
        )
        return {"status": "ok", "message": message.to_dict()}
    if command in {"run-once", "run"}:
        live_retrieval = _live_retrieval_config_for_args(args)
        if isinstance(live_retrieval, dict):
            return live_retrieval
        memory_store = _memory_store(args, create_default=True)
        artifact_store = _runtime_artifact_store(args)
        research_corpus_store = _runtime_corpus_store(args)
        runtime = ResidentRuntime(
            queue=queue,
            chat_runtime=_chat_runtime(
                journal,
                artifact_store=artifact_store,
                memory_store=memory_store,
                research_corpus_store=research_corpus_store,
                retrieval_operator=_build_live_retrieval_operator(
                    live_retrieval,
                    artifact_store=artifact_store,
                    corpus_store=research_corpus_store,
                )
                if live_retrieval is not None
                else None,
                thread_store=_thread_store(args, create_default=True),
                live_model=_agent_uses_live_model(args),
                model=getattr(args, "model", None),
                profile=getattr(args, "profile", "balanced"),
                thinking=_thinking_override(getattr(args, "thinking", "auto")),
                reasoning_effort=getattr(args, "reasoning_effort", "high"),
                max_output_tokens=getattr(args, "max_output_tokens", "provider"),
                temperature=getattr(args, "temperature", None),
                generation_mode=getattr(args, "generation_mode", "auto"),
                latency_target=getattr(args, "latency_target", "balanced"),
                response_language=_response_language_for_args(args),
                planner_mode=_processor_mode(args, "planner"),
                evaluator_mode=_processor_mode(args, "evaluator"),
                synthesizer_mode=_processor_mode(args, "synthesizer"),
                semantic_mode=_processor_mode(args, "semantic_intake"),
                turn_router_mode=_processor_mode(args, "turn_router"),
                default_mode=_chat_default_mode(args),
                execution_metadata=_runtime_execution_metadata(args),
            ),
            worker_id=args.worker_id,
            max_attempts=args.max_attempts,
            retry_backoff_ms=args.retry_backoff_ms,
            journal=journal,
            scheduler=ResidentScheduler(queue=queue, journal=journal) if args.tick_schedules else None,
            schedule_tick_limit=args.schedule_tick_limit,
        )
        if command == "run":
            return runtime.run_loop(
                max_iterations=args.max_iterations,
                max_duration_ms=args.max_duration_ms,
            ).to_dict()
        return runtime.run_once().to_dict()
    if command == "ack":
        outbox, reason = queue.transition_outbox_status(args.outbox_id, status=args.status)
        if outbox is None:
            return {"status": "failed", "reason": reason or "outbox_not_found", "outbox_id": args.outbox_id}
        journal.append(
            task_id=outbox.task_id,
            run_id="resident-cli",
            step_id=None,
            kind="resident_outbox_ack",
            data=resident_outbox_event(outbox),
            state_delta={"resident_outbox_status": outbox.status, "resident_outbox_id": outbox.outbox_id},
        )
        return {"status": "ok", "outbox": outbox.to_dict()}
    if command == "retry-outbox":
        outbox, reason = queue.retry_outbox(args.outbox_id, reason=args.reason)
        if outbox is None:
            return {"status": "failed", "reason": reason or "outbox_not_retryable_or_missing", "outbox_id": args.outbox_id}
        journal.append(
            task_id=outbox.task_id,
            run_id="resident-cli",
            step_id=None,
            kind="resident_outbox_retried",
            data=resident_outbox_event(outbox),
            state_delta={"resident_outbox_status": outbox.status, "resident_outbox_id": outbox.outbox_id},
        )
        return {"status": "ok", "outbox": outbox.to_dict()}
    return {"status": "failed", "reason": f"unknown_resident_command:{command}"}


def _resident_human_text(payload: dict[str, object]) -> str:
    lines: list[str] = []
    status = str(payload.get("status") or "unknown")
    lines.append(f"resident status: {status}")
    queue = payload.get("queue") if isinstance(payload.get("queue"), dict) else payload.get("queue_status")
    schedules = payload.get("schedules") if isinstance(payload.get("schedules"), dict) else payload.get("schedule_status")
    if isinstance(queue, dict):
        inbox_counts = queue.get("inbox_counts") if isinstance(queue.get("inbox_counts"), dict) else {}
        outbox_counts = queue.get("outbox_counts") if isinstance(queue.get("outbox_counts"), dict) else {}
        pending_input = int(outbox_counts.get("pending_user_input") or 0) + int(outbox_counts.get("pending_user_input_delivered") or 0)
        running = int(inbox_counts.get("running") or 0)
        lines.extend(
            [
                "",
                "queue",
                f"  claimable: {queue.get('claimable_count', 0)}",
                f"  running: {running}",
                f"  retry due: {queue.get('due_retry_count', 0)}",
                f"  stale running: {queue.get('stale_running_count', 0)}",
                f"  outbox ready: {queue.get('ready_outbox_count', 0)}",
                f"  pending input: {pending_input}",
                f"  dead letters: {queue.get('dead_letter_count', 0)}",
            ]
        )
        active_lease = queue.get("active_lease")
        if isinstance(active_lease, dict):
            lines.append(f"  active lease: {active_lease.get('worker_id')} until {active_lease.get('expires_at_ms')}")
    if isinstance(schedules, dict):
        lines.extend(
            [
                "",
                "schedules",
                f"  active: {schedules.get('active_count', 0)}",
                f"  due: {schedules.get('due_count', 0)}",
                f"  recurring: {schedules.get('recurring_count', 0)}",
                f"  unbounded: {schedules.get('unbounded_count', 0)}",
                f"  next due: {schedules.get('next_due_at_ms') or '-'}",
            ]
        )
    if isinstance(payload.get("message"), dict):
        lines.extend(["", "message", _resident_message_line(payload["message"])])
    if isinstance(payload.get("schedule"), dict):
        lines.extend(["", "schedule", _resident_schedule_line(payload["schedule"])])
    if isinstance(payload.get("tick"), dict):
        tick = payload["tick"]
        lines.extend(
            [
                "",
                "schedule tick",
                f"  status: {tick.get('status')}",
                f"  due: {tick.get('due_count', 0)} enqueued: {tick.get('enqueued_count', 0)} failed: {tick.get('failed_count', 0)}",
            ]
        )
        for item in _dict_list(tick.get("enqueued_messages"))[:5]:
            lines.append("  " + _resident_message_line(item).strip())
    for key in ("messages", "schedules"):
        values = _dict_list(payload.get(key))
        if values:
            lines.extend(["", key])
            formatter = _resident_schedule_line if key == "schedules" else _resident_message_line
            for item in values[:10]:
                lines.append(formatter(item))
            if len(values) > 10:
                lines.append(f"  ... {len(values) - 10} more")
    if isinstance(payload.get("inspection"), dict):
        _append_resident_inspection(lines, "queue inspection", payload["inspection"])
    if isinstance(payload.get("schedule_inspection"), dict):
        _append_resident_inspection(lines, "schedule inspection", payload["schedule_inspection"])
    if isinstance(payload.get("results"), list):
        lines.extend(["", "worker results"])
        for item in _dict_list(payload.get("results"))[:10]:
            lines.append(f"  {item.get('status')} message={item.get('message_id') or '-'} reason={item.get('reason') or '-'}")
    if isinstance(payload.get("payload"), dict):
        payload_detail = payload["payload"]
        if isinstance(payload_detail.get("schedule_tick"), dict):
            tick = payload_detail["schedule_tick"]
            lines.extend(
                [
                    "",
                    "schedule tick",
                    f"  status: {tick.get('status')} due={tick.get('due_count', 0)} enqueued={tick.get('enqueued_count', 0)}",
                ]
            )
    reason = payload.get("reason")
    if reason:
        lines.extend(["", f"reason: {reason}"])
    return "\n".join(lines)


def _append_resident_inspection(lines: list[str], title: str, inspection: dict[str, object]) -> None:
    lines.extend(["", title, f"  status: {inspection.get('status')}"])
    for issue in _dict_list(inspection.get("issues"))[:10]:
        lines.append(f"  {issue.get('severity', 'info')}: {issue.get('code')} count={issue.get('count', '-')}")
    actions = inspection.get("recommended_actions")
    if isinstance(actions, list) and actions:
        lines.append("  actions: " + "; ".join(str(item) for item in actions[:5]))


def _resident_message_line(message: dict[str, object]) -> str:
    text = str(message.get("text") or message.get("text_preview") or "")
    preview = text[:80].replace("\n", " ")
    return (
        f"  {message.get('message_id') or message.get('outbox_id')} "
        f"p={message.get('priority', 0)} status={message.get('status')} "
        f"thread={message.get('thread_id')} text={preview!r}"
    )


def _resident_schedule_line(schedule: dict[str, object]) -> str:
    text = str(schedule.get("text") or schedule.get("text_preview") or "")
    preview = text[:80].replace("\n", " ")
    return (
        f"  {schedule.get('schedule_id')} p={schedule.get('priority', 0)} "
        f"status={schedule.get('status')} due={schedule.get('next_due_at_ms') or '-'} "
        f"runs={schedule.get('run_count', 0)}/{schedule.get('max_runs') or '∞'} "
        f"thread={schedule.get('thread_id')} text={preview!r}"
    )


def _dict_list(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def _combined_health(*statuses: str) -> str:
    order = {"ok": 0, "attention": 1, "needs_review": 2, "warning": 3, "error": 4}
    highest = max(statuses, key=lambda status: order.get(status, 1))
    return highest if highest in order else "attention"


def _agent_uses_live_model(args) -> bool:
    if bool(getattr(args, "online", False)):
        return True
    return any(
        value == "model"
        for value in (
            getattr(args, "planner", "fake"),
            getattr(args, "evaluator", "fake"),
            getattr(args, "synthesizer", "fake"),
            getattr(args, "semantic_intake", "fake"),
            getattr(args, "turn_router", "fake"),
        )
    )


def _chat_live_model_block(args) -> JsonObject | None:
    if not _agent_uses_live_model(args):
        return None
    if str(os.environ.get("DEEPSEEK_API_KEY", "") or "").strip():
        return None
    if os.environ.get("HOLO_V3_LIVE_MODEL") == "1":
        return None
    return {"status": "blocked", "reason": "live_model_not_enabled"}


def _processor_mode(args, name: str) -> str:
    value = getattr(args, name, "fake")
    if bool(getattr(args, "online", False)) and value == "fake":
        return "model"
    return value


def _agent_mode(args) -> str:
    mode = getattr(args, "mode", "auto")
    if mode == "auto" and getattr(args, "research_profile", None):
        return "retrieval"
    return str(mode)


def _chat_default_mode(args) -> str:
    if _live_retrieval_explicitly_enabled(args) or getattr(args, "research_profile", None):
        return "retrieval"
    return "auto"


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
    max_output_tokens: object = "provider",
    temperature: float | None = None,
    generation_mode: str = "auto",
    latency_target: str = "balanced",
) -> ProcessorFabric:
    providers = {
        "deepseek": DeepSeekProvider(enabled=True, model=model, max_retries=2),
        "openai_compatible": OpenAICompatibleProvider(enabled=True, model=model or "local-model", max_retries=2),
    }
    if provider == "deepseek":
        router = deepseek_v4_router(
            profile=profile,
            model=model,
            thinking=thinking,
            reasoning_effort=reasoning_effort,
            max_output_tokens=max_output_tokens,
            temperature=temperature,
            generation_mode=generation_mode,
            latency_target=latency_target,
        )
    else:
        router = ProcessorRouter(default_provider=provider, default_model=providers[provider].model)
    return ProcessorFabric(
        providers=providers,
        router=router,
        journal=journal,
    )


def _model_packet_payload(args) -> dict[str, object]:
    provider_name = str(getattr(args, "provider", "deepseek"))
    thinking = _thinking_override(getattr(args, "thinking", "auto"))
    if provider_name == "deepseek":
        router = deepseek_v4_router(
            profile=getattr(args, "profile", "balanced"),
            model=getattr(args, "model", None),
            thinking=thinking,
            reasoning_effort=getattr(args, "reasoning_effort", "high"),
            max_output_tokens=getattr(args, "max_output_tokens", "provider"),
            temperature=getattr(args, "temperature", None),
            generation_mode=getattr(args, "generation_mode", "auto"),
            latency_target=getattr(args, "latency_target", "balanced"),
        )
        provider = DeepSeekProvider(enabled=True, model=getattr(args, "model", None))
    else:
        provider = OpenAICompatibleProvider(enabled=True, model=getattr(args, "model", None) or "local-model")
        router = ProcessorRouter(default_provider=provider_name, default_model=provider.model)
    task_type = str(getattr(args, "task_type", "planner.propose"))
    route = router.route(
        task_type,
        provider=provider_name,
        model=getattr(args, "model", None),
        timeout_seconds=getattr(args, "timeout_seconds", None),
    )
    parameters: JsonObject = dict(route.parameters)
    parameters.setdefault("generation_mode", getattr(args, "generation_mode", "auto"))
    parameters.setdefault("latency_target", getattr(args, "latency_target", "balanced"))
    if thinking is not None:
        parameters["thinking"] = thinking
        parameters["thinking_locked"] = True
    max_tokens = getattr(args, "max_tokens", None)
    if max_tokens is not None:
        parameters["max_tokens"] = max_tokens
    temperature = getattr(args, "temperature", None)
    if temperature is not None:
        parameters["temperature"] = temperature
        parameters["temperature_locked"] = True
    parameters.update(
        {
            "task_type": task_type,
            "provider": route.provider,
            "model": route.model,
            "timeout_seconds": route.timeout_seconds,
        }
    )
    prompt = _packet_prompt(task_type, str(getattr(args, "goal", "")))
    parameters = adapt_generation_parameters(task_type=task_type, prompt=prompt, parameters=parameters)
    parameters["task_type"] = task_type
    parameters["provider"] = route.provider
    parameters.setdefault("model", route.model)
    request = ProcessorRequest(
        request_id="proc-packet-preview",
        run_id="run-packet-preview",
        processor=task_type,
        prompt=prompt,
        context_id="ctx-packet-preview",
        parameters=parameters,
    )
    packet = provider.packet_preview(request, include_prompt=bool(getattr(args, "show_prompt", False)))
    return {
        "status": "ok",
        "network_call": False,
        "availability": provider.availability(),
        "route": {
            "task_type": route.task_type,
            "provider": route.provider,
            "model": parameters.get("model", route.model),
            "timeout_seconds": parameters.get("timeout_seconds", route.timeout_seconds),
            "parameters": parameters,
        },
        "request": {
            "request_id": request.request_id,
            "processor": request.processor,
            "context_id": request.context_id,
            "prompt_chars": len(request.prompt),
        },
        "packet": packet,
    }


def _packet_prompt(task_type: str, goal: str) -> str:
    if task_type == "chat.route":
        payload = {
            "contract": CHAT_ROUTE_PROMPT_CONTRACT,
            "user_turn": goal,
            "thread_state": {
                "active_task_id": None,
                "pending_question": None,
                "last_result_status": None,
                "recent_turns": [],
            },
        }
    elif task_type == "semantic.intake":
        payload = {
            "contract": SEMANTIC_INTAKE_PROMPT_CONTRACT,
            "user_goal": goal,
            "host_capability_catalog": semantic_capability_catalog(),
        }
    elif task_type == "evaluator.assess":
        payload = {
            "contract": EVALUATOR_PROMPT_CONTRACT,
            "context": {"goal": goal, "mode": "auto", "evidence_refs": [], "citation_refs": []},
            "observation": {
                "kind": "response",
                "status": "ok",
                "content": {"text": "Host observation preview goes here."},
            },
        }
    elif task_type == "synthesizer.answer":
        payload = {
            "contract": SYNTHESIZER_PROMPT_CONTRACT,
            "retrieval_report": {
                "report_id": "report-preview",
                "status": "sufficient",
                "preview": "Evidence preview goes here.",
            },
            "evidence": [{"evidence_id": "ev-1", "text_preview": "Evidence preview goes here."}],
            "citations": [{"citation_id": "cite-1", "evidence_id": "ev-1", "quote_preview": "Evidence preview goes here."}],
        }
    elif task_type == "task.compile":
        payload = {
            "contract": "Return exactly one JSON object matching task.compile.",
            "schema": "holo.kernel_v3.task_compile_input.preview",
            "objective": goal,
            "domain": "finance",
            "instruction": (
                "Produce TaskSpec, EvidenceSpec, TransformSpec, SlotFrame, and tool_chain_plan. "
                "Use semantic judgment over the objective; host validates and executes tools."
            ),
            "target_binding": {},
            "fact_ledger": [],
            "host_fallback_program": {
                "task_spec": {"task_type": "unknown", "objective": goal, "success_criteria": []},
                "evidence_specs": [],
                "transform_specs": [],
                "slot_frame": {"required_slots": [], "missing_slots": []},
            },
        }
    elif task_type == "mission.assess":
        payload = {
            "contract": MISSION_ASSESS_PROMPT_CONTRACT,
            "mission_state": {
                "mission_id": "mission-preview",
                "root_goal": goal,
                "status": "running",
                "open_gaps": ["official evidence"],
            },
            "agent_result": {"status": "failed", "failure_report": {"reason": "retrieval_empty"}},
            "run_delta": {"actions": [{"name": "retrieval.run"}], "evidence_refs": [], "citation_refs": []},
        }
    elif task_type == "workmethod.frame":
        payload = {
            "contract": WORKMETHOD_FRAME_PROMPT_CONTRACT,
            "goal": goal,
            "thread_id": "preview-thread",
            "semantic_intake": {
                "primary_intent": "research",
                "suggested_mode": "retrieval_answer",
                "requires_clarification": False,
                "intents": [],
            },
            "task_execution_plan": {
                "selected_mode": "retrieval_answer",
                "steps": [{"goal": goal, "tool_name": "retrieval.run"}],
            },
            "answer_profile": {
                "format": "detailed_report",
                "detail_level": "detailed",
                "target_sections": ["结论", "证据", "局限"],
            },
            "execution_metadata": {
                "thread_rag_context": {"recent_turns": [], "recent_task_trace": []},
                "mission_context": {"mission_state": {"open_gaps": [goal]}},
            },
        }
    elif task_type == "workmethod.gap":
        payload = {
            "contract": WORKMETHOD_GAP_PROMPT_CONTRACT,
            "root_goal": goal,
            "workmethod": {
                "frame": {"done_criteria": ["answer the user's goal with evidence"]},
                "method": {"method_name": "goal_directed_research"},
            },
            "run_delta": {
                "actions": [{"name": "retrieval.run"}],
                "retrieval_reports": [{"status": "insufficient", "attempted_queries": [goal]}],
                "evidence_refs": [],
                "citation_refs": [],
            },
            "agent_result": {"status": "failed", "failure_report": {"reason": "insufficient_evidence"}},
            "mission_assessment": {"decision": "continue", "missing_requirements": [goal]},
        }
    else:
        payload = {
            "contract": PLANNER_PROMPT_CONTRACT,
            "dialogue": [{"role": "user", "content": goal}],
            "context": {
                "identity": "Holo Kernel v3 host-owned agent harness.",
                "host_rules": [
                    "The model proposes; the host validates, executes, journals, and stops.",
                    "Return exactly one JSON object matching planner.propose.",
                    "Do not invent tools. Use ask_user when scope or permission is missing.",
                    "For roleplay/persona replies, do not use parenthesized stage directions unless the user explicitly asks for them.",
                ],
                "available_tools": [
                    {"name": "retrieval.run", "side_effect_class": "network"},
                    {"name": "workspace.search", "side_effect_class": "read"},
                    {"name": "file.read", "side_effect_class": "read"},
                    {"name": "workspace.write", "side_effect_class": "write"},
                    {"name": "respond", "side_effect_class": "none"},
                    {"name": "ask_user", "side_effect_class": "none"},
                ],
            },
        }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def _retrieval_provider_command(args) -> dict[str, object]:
    if args.mode == "live-http":
        config = _live_retrieval_config_from_args(args, enable=_live_retrieval_requested(args))
        operator = config.build_operator()
        inspection = inspect_retrieval_providers(operator, research_profile_id=args.profile)
        return {
            "status": inspection.status,
            "mode": "live-http",
            "network_access": inspection.network_access,
            "provider_capabilities": inspection.provider_capabilities,
            "inspection": inspection.to_dict(),
            "live_config": config.safe_diagnostics(),
        }
    operator, mode = _retrieval_operator_for_mode(args.mode, args)
    inspection = inspect_retrieval_providers(operator, research_profile_id=args.profile)
    return {
        "status": inspection.status,
        "mode": mode,
        "network_access": inspection.network_access,
        "provider_capabilities": inspection.provider_capabilities,
        "inspection": inspection.to_dict(),
    }


def _retrieval_operator_for_mode(mode: str, args) -> tuple[RetrievalOperator, str]:
    if mode == "corpus":
        corpus_store = _corpus_store(args, create_default=True)
        artifact_store = _artifact_store(args, create_default=False) or ArtifactStore.in_memory()
        if corpus_store is None:
            return _unconfigured_retrieval_operator(), "unconfigured"
        return (
            RetrievalOperator(
                search_provider=CorpusSearchProvider(corpus_store),
                fetch_provider=CorpusFetchProvider(artifact_store),
            ),
            "corpus",
        )
    corpus_store = _runtime_corpus_store(args)
    artifact_store = _runtime_artifact_store(args) or ArtifactStore.in_memory()
    if corpus_store is None:
        return _unconfigured_retrieval_operator(), "unconfigured"
    return _inspectable_retrieval_operator(artifact_store=artifact_store, corpus_store=corpus_store), "default"


def _inspectable_retrieval_operator(
    *,
    artifact_store: ArtifactStore,
    corpus_store: ResearchCorpusStore | None,
) -> RetrievalOperator:
    if corpus_store is None:
        return _unconfigured_retrieval_operator()
    return RetrievalOperator(
        search_provider=CorpusSearchProvider(corpus_store),
        fetch_provider=CorpusFetchProvider(artifact_store),
    )


def _unconfigured_retrieval_operator() -> RetrievalOperator:
    return RetrievalOperator(
        search_provider=UnconfiguredSearchProvider(reason="retrieval_source_not_configured"),
        fetch_provider=UnconfiguredFetchProvider(reason="retrieval_fetch_not_configured"),
    )


def _run_retrieve(
    journal: JournalStore,
    *,
    query: str,
    body: str | None,
    synthesizer_mode: str,
    artifact_store: ArtifactStore | None = None,
    corpus_store: ResearchCorpusStore | None = None,
    retrieval_operator: RetrievalOperator | None = None,
    source_uri: str = "inline://holo-v3-cli",
    source_title: str = "Holo v3 CLI evidence",
    research_profile_id: str | None = None,
    max_queries: int | None = None,
    max_sources: int = 5,
    max_fetches: int = 3,
    max_spans_per_document: int = 1,
    from_corpus: bool = False,
    index_corpus: bool = False,
) -> dict[str, object]:
    artifacts = artifact_store or ArtifactStore.in_memory()
    goal = SearchGoal(
        goal_id="goal-cli",
        query=query,
        max_queries=_positive_limit(max_queries) if max_queries is not None else _default_cli_query_count(
            research_profile_id=research_profile_id,
            max_sources=max_sources,
            max_fetches=max_fetches,
        ),
        max_sources=_positive_limit(max_sources),
        max_fetches=_positive_limit(max_fetches),
        max_spans_per_document=_positive_limit(max_spans_per_document),
        metadata=_research_metadata(research_profile_id),
    )
    active_corpus = corpus_store if index_corpus else None
    if from_corpus:
        if corpus_store is None:
            return {"status": "failed", "reason": "corpus_store_not_configured"}
        operator = RetrievalOperator(
            search_provider=CorpusSearchProvider(corpus_store),
            fetch_provider=CorpusFetchProvider(artifacts),
            corpus_store=active_corpus,
        )
        mode = "corpus"
    elif retrieval_operator is not None:
        operator = retrieval_operator
        mode = "live-http"
    else:
        if body is None:
            return {"status": "failed", "reason": "retrieval_source_not_configured"}
        source = SearchSource(
            source_id="src-cli-1",
            uri=source_uri,
            title=source_title,
            snippet=query,
            provider="inline_user_body",
        )
        operator = RetrievalOperator(
            search_provider=_InlineSearchProvider(source),
            fetch_provider=_InlineFetchProvider(source.uri, body),
            corpus_store=active_corpus,
        )
        mode = "inline"
    report = operator.run(
        goal,
        journal=journal,
        artifact_store=artifacts,
        task_id="task-cli-retrieve",
        run_id="run-cli-retrieve",
        step_id_prefix="cli-retrieve",
    )
    payload: dict[str, object] = {
        "status": "ok",
        "mode": mode,
        "network_access": operator.network_access,
        "provider_capabilities": operator.provider_capabilities(),
        "report": report.to_dict(),
    }
    if corpus_store is not None:
        payload["corpus_documents"] = [
            record.data
            for record in journal.records(task_id="task-cli-retrieve", kind="retrieval_corpus_document")
            if isinstance(record.data, dict)
        ]
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


class _InlineSearchProvider:
    provider_id = "inline_user_body_search"
    live_network = False
    default_enabled = True
    profile_aware = False
    supported_research_profiles: list[str] = []

    def __init__(self, source: SearchSource) -> None:
        self.source = source

    def search(self, query: str, *, goal: SearchGoal, plan) -> list[SearchSource]:
        return [self.source]


class _InlineFetchProvider:
    provider_id = "inline_user_body_fetch"
    live_network = False
    default_enabled = True
    profile_aware = False
    supported_research_profiles: list[str] = []

    def __init__(self, uri: str, body: str) -> None:
        self.uri = uri
        self.body = body

    def fetch(self, source: SearchSource) -> FetchResponse:
        if source.uri != self.uri:
            return FetchResponse(status="failed", body="", diagnostics={"reason": "inline_uri_mismatch", "uri": source.uri})
        return FetchResponse(status="ok", body=self.body)


def _research_metadata(research_profile_id: str | None) -> dict[str, object]:
    if research_profile_id is None:
        return {}
    return {
        "research_profile": research_profile_id,
        "research_depth": DEFAULT_RESEARCH_DEPTH,
        "search_strategy": DEFAULT_LIVE_SEARCH_STRATEGY,
        "query_campaign": "auto",
    }


def _positive_limit(value: int, *, default: int = 20) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(1, parsed)


def _default_cli_query_count(*, research_profile_id: str | None, max_sources: int, max_fetches: int) -> int:
    if research_profile_id:
        return 8
    if _positive_limit(max_sources, default=0) >= 16 or _positive_limit(max_fetches, default=0) >= 16:
        return 8
    return 1


def _exception_reason(exc: Exception) -> str:
    if isinstance(exc, KeyError) and exc.args:
        return str(exc.args[0])
    return str(exc) or type(exc).__name__


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
                    "chat.route": "deepseek-v4-flash",
                    "semantic.intake": "deepseek-v4-flash",
                    "planner.propose": "deepseek-v4-flash",
                    "evaluator.assess": "deepseek-v4-flash",
                    "synthesizer.answer": "deepseek-v4-flash",
                },
                "balanced": {
                    "chat.route": "deepseek-v4-flash",
                    "semantic.intake": "deepseek-v4-flash",
                    "planner.propose": "deepseek-v4-flash",
                    "evaluator.assess": "deepseek-v4-flash",
                    "synthesizer.answer": "deepseek-v4-flash",
                },
                "quality": {
                    "chat.route": "deepseek-v4-flash",
                    "semantic.intake": "deepseek-v4-pro",
                    "planner.propose": "deepseek-v4-pro",
                    "evaluator.assess": "deepseek-v4-pro",
                    "synthesizer.answer": "deepseek-v4-pro",
                },
            },
            "thinking": {"default": "disabled", "choices": ["auto", "enabled", "disabled"]},
            "reasoning_effort": {"default": "medium", "choices": ["low", "medium", "high", "max"]},
            "generation_mode": {"default": "auto", "choices": ["auto", "manual"]},
            "latency_target": {"default": "balanced", "choices": ["fast", "balanced", "quality", "thorough"]},
            "packet_inspection": "holo-v3 model-packet --provider deepseek --task-type planner.propose --goal '<goal>'",
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
