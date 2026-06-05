from __future__ import annotations

import argparse
import inspect
import json
import os
import sys
import urllib.parse
from pathlib import Path

from kernel_v3.agent import AgentRuntime
from kernel_v3.agent.contracts import SemanticIntake
from kernel_v3.capabilities import semantic_capability_catalog
from kernel_v3.chat import ChatRuntime
from kernel_v3.chat.console import (
    ChatConsoleOptions,
    chat_color_enabled,
    chat_output_mode,
    print_chat_turn_human,
    render_chat_result,
    render_status_notice,
    run_chat_console,
)
from kernel_v3.chat.thread_store import ThreadTranscriptStore
from kernel_v3.context import ArtifactStore, ContextCompiler, ContextPackCompiler, merge_context_budget
from kernel_v3.contracts import JsonObject, ProcessorRequest
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
)
from kernel_v3.retrieval.live_config import (
    LIVE_ALLOW_ALL_HOSTS_ENV,
    LIVE_CRAWL_INCLUDE_SITEMAPS_ENV,
    LIVE_CRAWL_MAX_LINKS_PER_PAGE_ENV,
    LIVE_CRAWL_MAX_PAGES_ENV,
    LIVE_CRAWL_MAX_SITEMAP_URLS_ENV,
    LIVE_CRAWL_MAX_SOURCE_DIRECTORY_SEEDS_ENV,
    LIVE_CRAWL_SEED_URLS_ENV,
    LIVE_CRAWL_SOURCE_DIRECTORY_ENV,
    LIVE_FETCH_DISCOVERED_SEARCH_HOSTS_ENV,
    LIVE_FETCH_ALLOWED_HOSTS_ENV,
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
from kernel_v3.resident import ResidentDoctor, ResidentQueue, ResidentRuntime, ResidentScheduler
from kernel_v3.resident.projection import resident_doctor_event, resident_inbox_event, resident_outbox_event
from kernel_v3.storage import (
    default_journal_index_path,
    default_journal_path,
    default_memory_index_path,
    default_memory_log_path,
    default_thread_root,
)
from kernel_v3.testing.fakes import FakeEvaluator, FakePlanner
from kernel_v3.tools import ToolRegistry
from kernel_v3.trace import TraceRenderer


DEFAULT_LIVE_NETWORK_FETCH_BUDGET = 409_600
DEFAULT_LIVE_RETRIEVAL_FETCH_BUDGET = 4_096
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
        choices=["chat.route", "semantic.intake", "planner.propose", "evaluator.assess", "synthesizer.answer", "mission.assess"],
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
    journal = JournalStore(Path(args.journal), index_path=Path(args.index))

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
                print(json.dumps(payload.to_dict(), ensure_ascii=False, sort_keys=True))
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
        agent_runtime=_mission_runtime(agent_runtime, live_model=live_model),
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
    metadata["interaction_preferences"] = {
        "response_language": response_language,
    }
    metadata["context_budget"] = merge_context_budget(
        getattr(args, "context_profile", "compact"),
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
        metadata["agent_loop"] = loop_budget
    research_profile = getattr(args, "research_profile", None)
    if isinstance(research_profile, str) and research_profile:
        research_depth = str(getattr(args, "research_depth", "balanced") or "balanced")
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
        return {"status": "blocked", "reason": "missing_deepseek_api_key"}
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
        "deepseek": DeepSeekProvider(enabled=True, model=model),
        "openai_compatible": OpenAICompatibleProvider(enabled=True, model=model or "local-model"),
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
