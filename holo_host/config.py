from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .common import ensure_directory

DEFAULT_BLOCKED_KEYWORDS = (
    "wire transfer",
    "routing number",
    "bank account",
    "诊断",
    "处方",
    "prescription",
    "lawsuit",
    "诉讼",
    "税务建议",
    "tax advice",
    "投资建议",
    "investment advice",
    "wallet seed",
    "助记词",
    "私钥",
    "password reset",
)


@dataclass(slots=True)
class RuntimeConfig:
    repo_root: Path
    state_dir: Path
    db_path: Path
    log_dir: Path
    processor_backend: str = "auto"
    codex_binary: str = "codex"
    codex_command_prefix: tuple[str, ...] = ()
    codex_extra_args: tuple[str, ...] = ()
    codex_timeout_seconds: int = 900
    codex_model: str = ""
    codex_reasoning_effort: str = ""
    fast_model: str = "gpt-5.4-mini"
    fast_reasoning_effort: str = "low"
    fast_history_messages: int = 3
    responses_model: str = "gpt-5.4"
    responses_fast_model: str = "gpt-5.4-mini"
    network_enabled: bool = True
    image_enabled: bool = True
    poll_interval_seconds: int = 60
    max_jobs_per_cycle: int = 4
    dry_run: bool = False
    resume_sessions: bool = True
    api_bind_host: str = "127.0.0.1"
    api_port: int = 8000


@dataclass(slots=True)
class MailConfig:
    transport: str = "maildir"
    mailbox: str = "INBOX"
    poll_limit: int = 10
    mark_seen_after_fetch: bool = True
    imap_host: str = ""
    imap_port: int = 993
    smtp_host: str = ""
    smtp_port: int = 587
    username: str = ""
    password_env: str = "HOLO_MAIL_PASSWORD"
    sent_from: str = ""
    maildir_inbox: Path = Path(".holo_runtime/mail/inbox")
    maildir_processed: Path = Path(".holo_runtime/mail/processed")
    maildir_outbox: Path = Path(".holo_runtime/mail/outbox")


@dataclass(slots=True)
class MemoryConfig:
    recall_trigger_mode: str = "adaptive"
    prompt_top_k: int = 4
    mind_graph_db_path: Path = Path(".holo_runtime/mind_graph.sqlite3")
    graph_led_reply: bool = True
    graph_fallback: bool = True
    deep_recall_on_memory_queries: bool = True
    recall_reconstruct_enabled: bool = True
    vector_backend: str = "milvus"
    milvus_uri: str = ".holo_runtime/milvus/memory_fabric.db"
    milvus_collection_prefix: str = "holo_memory"
    activation_cache_enabled: bool = True
    private_memory_sync_enabled: bool = False
    private_memory_repo_path: str = ""
    brain_mode_default: str = "full_brain"
    heartbeat_interval_seconds: int = 1
    attention_tick_interval_seconds: int = 3
    dream_idle_threshold_seconds: int = 900
    self_revision_interval_seconds: int = 1800
    self_revision_enabled: bool = True
    self_revision_min_evidence: int = 3
    self_model_refresh_interval_seconds: int = 300
    homeostasis_tick_interval_seconds: int = 120
    affect_tick_interval_seconds: int = 90
    drive_arbitration_interval_seconds: int = 120
    initiative_marketplace_interval_seconds: int = 180
    outcome_appraisal_interval_seconds: int = 240
    operator_planning_interval_seconds: int = 420
    operator_shadow_cycle_interval_seconds: int = 300
    visual_ingest_cycle_interval_seconds: int = 45
    visual_sync_max_size_mb: int = 8
    visual_sync_max_count: int = 1
    operator_shadow_root: str = ".holo_runtime/operator_shadow"
    auto_observe: bool = True
    promote_batch_size: int = 8
    promote_interval_seconds: int = 300
    maintenance_stream_interval_seconds: int = 60
    dream_interval_seconds: int = 1800
    thought_interval_seconds: int = 900
    reflection_interval_seconds: int = 1800
    initiative_interval_seconds: int = 1800
    association_stream_interval_seconds: int = 180
    social_stream_interval_seconds: int = 300
    deep_dream_cycle_interval_seconds: int = 3600
    dream_sample_size: int = 6
    thought_sample_size: int = 4
    reflection_window_hours: float = 12.0
    history_messages: int = 8
    fast_history_messages: int = 4
    recall_history_messages: int = 8
    fast_episodic_k: int = 2
    recall_episodic_k: int = 4
    fast_consciousness_k: int = 1
    recall_consciousness_k: int = 2
    active_wechat_history_enabled: bool = True
    active_wechat_history_limit: int = 40
    active_wechat_history_page_turns: int = 8
    active_wechat_history_cooldown_seconds: int = 180
    active_wechat_history_timeout_seconds: int = 180
    active_wechat_history_deep_limit: int = 120
    active_wechat_history_deep_page_turns: int = 24
    active_wechat_history_deep_cooldown_seconds: int = 15
    active_wechat_history_deep_timeout_seconds: int = 300
    active_wechat_history_include_visible: bool = True
    active_wechat_history_include_captures: bool = False


@dataclass(slots=True)
class AutonomyConfig:
    auto_send_mode: str = "full_auto"
    allow_proactive_existing_threads: bool = True
    allow_initiative_whitelist_contacts: bool = True
    initiative_probe_enabled: bool = True
    game_state_enabled: bool = True
    proactive_after_hours: int = 72
    initiative_cooldown_hours: int = 12
    max_auto_replies_per_contact_per_hour: int = 4
    wechat_helper_config_path: str = ""
    wechat_helper_windows_repo_root: str = ""
    blocked_keywords: tuple[str, ...] = field(default_factory=lambda: DEFAULT_BLOCKED_KEYWORDS)


@dataclass(slots=True)
class HostConfig:
    runtime: RuntimeConfig
    mail: MailConfig
    memory: MemoryConfig
    autonomy: AutonomyConfig
    config_path: Path | None = None


def _read_toml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return tomllib.loads(path.read_text(encoding="utf-8"))


def _resolve_path(repo_root: Path, state_dir: Path, raw: str | None, fallback: str) -> Path:
    base = raw or fallback
    path = Path(base)
    if not path.is_absolute():
        path = repo_root / path
    if ".holo_runtime" not in str(path):
        path = state_dir / path.name if path.parent == Path(".") else path
    return path


def load_config(config_path: str | None = None, repo_root: str | Path | None = None) -> HostConfig:
    root = Path(repo_root or Path(__file__).resolve().parents[1]).resolve()
    chosen_path = Path(config_path).expanduser().resolve() if config_path else root / ".holo_host.toml"
    data = _read_toml(chosen_path)

    runtime_data = data.get("runtime", {})
    state_dir = _resolve_path(root, root / ".holo_runtime", runtime_data.get("state_dir"), ".holo_runtime")
    log_dir = _resolve_path(root, state_dir, runtime_data.get("log_dir"), ".holo_runtime/logs")
    db_path = _resolve_path(root, state_dir, runtime_data.get("db_path"), ".holo_runtime/holo_host.sqlite3")

    runtime = RuntimeConfig(
        repo_root=root,
        state_dir=state_dir,
        db_path=db_path,
        log_dir=log_dir,
        processor_backend=str(runtime_data.get("processor_backend", "auto")).strip() or "auto",
        codex_binary=str(runtime_data.get("codex_binary", "codex")),
        codex_command_prefix=tuple(str(item) for item in runtime_data.get("codex_command_prefix", [])),
        codex_extra_args=tuple(str(item) for item in runtime_data.get("codex_extra_args", [])),
        codex_timeout_seconds=int(runtime_data.get("codex_timeout_seconds", 900)),
        codex_model=str(runtime_data.get("codex_model", "")),
        codex_reasoning_effort=str(runtime_data.get("codex_reasoning_effort", "")),
        fast_model=str(runtime_data.get("fast_model", "gpt-5.4-mini")),
        fast_reasoning_effort=str(runtime_data.get("fast_reasoning_effort", "low")),
        fast_history_messages=int(runtime_data.get("fast_history_messages", 3)),
        responses_model=str(runtime_data.get("responses_model", runtime_data.get("codex_model", "gpt-5.4"))),
        responses_fast_model=str(runtime_data.get("responses_fast_model", runtime_data.get("fast_model", "gpt-5.4-mini"))),
        network_enabled=bool(runtime_data.get("network_enabled", True)),
        image_enabled=bool(runtime_data.get("image_enabled", True)),
        poll_interval_seconds=int(runtime_data.get("poll_interval_seconds", 60)),
        max_jobs_per_cycle=int(runtime_data.get("max_jobs_per_cycle", 4)),
        dry_run=bool(runtime_data.get("dry_run", False)),
        resume_sessions=bool(runtime_data.get("resume_sessions", True)),
        api_bind_host=str(runtime_data.get("api_bind_host", "127.0.0.1")),
        api_port=int(runtime_data.get("api_port", 8000)),
    )

    mail_data = data.get("mail", {})
    mail = MailConfig(
        transport=str(mail_data.get("transport", "maildir")),
        mailbox=str(mail_data.get("mailbox", "INBOX")),
        poll_limit=int(mail_data.get("poll_limit", 10)),
        mark_seen_after_fetch=bool(mail_data.get("mark_seen_after_fetch", True)),
        imap_host=str(mail_data.get("imap_host", "")),
        imap_port=int(mail_data.get("imap_port", 993)),
        smtp_host=str(mail_data.get("smtp_host", "")),
        smtp_port=int(mail_data.get("smtp_port", 587)),
        username=str(mail_data.get("username", "")),
        password_env=str(mail_data.get("password_env", "HOLO_MAIL_PASSWORD")),
        sent_from=str(mail_data.get("sent_from", "")),
        maildir_inbox=_resolve_path(root, state_dir, mail_data.get("maildir_inbox"), ".holo_runtime/mail/inbox"),
        maildir_processed=_resolve_path(root, state_dir, mail_data.get("maildir_processed"), ".holo_runtime/mail/processed"),
        maildir_outbox=_resolve_path(root, state_dir, mail_data.get("maildir_outbox"), ".holo_runtime/mail/outbox"),
    )

    memory_data = data.get("memory", {})
    recall_history_messages = int(memory_data.get("recall_history_messages", memory_data.get("history_messages", 8)))
    memory = MemoryConfig(
        recall_trigger_mode=str(memory_data.get("recall_trigger_mode", "adaptive")).strip() or "adaptive",
        prompt_top_k=int(memory_data.get("prompt_top_k", 4)),
        mind_graph_db_path=_resolve_path(root, state_dir, memory_data.get("mind_graph_db_path"), ".holo_runtime/mind_graph.sqlite3"),
        graph_led_reply=bool(memory_data.get("graph_led_reply", True)),
        graph_fallback=bool(memory_data.get("graph_fallback", True)),
        deep_recall_on_memory_queries=bool(memory_data.get("deep_recall_on_memory_queries", True)),
        recall_reconstruct_enabled=bool(memory_data.get("recall_reconstruct_enabled", True)),
        vector_backend=str(memory_data.get("vector_backend", "milvus")).strip() or "milvus",
        milvus_uri=str(memory_data.get("milvus_uri", ".holo_runtime/milvus/memory_fabric.db")).strip()
        or ".holo_runtime/milvus/memory_fabric.db",
        milvus_collection_prefix=str(memory_data.get("milvus_collection_prefix", "holo_memory")).strip() or "holo_memory",
        activation_cache_enabled=bool(memory_data.get("activation_cache_enabled", True)),
        private_memory_sync_enabled=bool(memory_data.get("private_memory_sync_enabled", False)),
        private_memory_repo_path=str(memory_data.get("private_memory_repo_path", "")).strip(),
        brain_mode_default=str(memory_data.get("brain_mode_default", "full_brain")).strip() or "full_brain",
        heartbeat_interval_seconds=int(memory_data.get("heartbeat_interval_seconds", 1)),
        attention_tick_interval_seconds=int(memory_data.get("attention_tick_interval_seconds", 3)),
        dream_idle_threshold_seconds=int(memory_data.get("dream_idle_threshold_seconds", 900)),
        self_revision_interval_seconds=int(memory_data.get("self_revision_interval_seconds", 1800)),
        self_revision_enabled=bool(memory_data.get("self_revision_enabled", True)),
        self_revision_min_evidence=int(memory_data.get("self_revision_min_evidence", 3)),
        self_model_refresh_interval_seconds=int(memory_data.get("self_model_refresh_interval_seconds", 300)),
        homeostasis_tick_interval_seconds=int(memory_data.get("homeostasis_tick_interval_seconds", 120)),
        affect_tick_interval_seconds=int(memory_data.get("affect_tick_interval_seconds", 90)),
        drive_arbitration_interval_seconds=int(memory_data.get("drive_arbitration_interval_seconds", 120)),
        initiative_marketplace_interval_seconds=int(memory_data.get("initiative_marketplace_interval_seconds", 180)),
        outcome_appraisal_interval_seconds=int(memory_data.get("outcome_appraisal_interval_seconds", 240)),
        operator_planning_interval_seconds=int(memory_data.get("operator_planning_interval_seconds", 420)),
        operator_shadow_cycle_interval_seconds=int(memory_data.get("operator_shadow_cycle_interval_seconds", 300)),
        visual_ingest_cycle_interval_seconds=int(memory_data.get("visual_ingest_cycle_interval_seconds", 45)),
        visual_sync_max_size_mb=int(memory_data.get("visual_sync_max_size_mb", 8)),
        visual_sync_max_count=int(memory_data.get("visual_sync_max_count", 1)),
        operator_shadow_root=str(memory_data.get("operator_shadow_root", ".holo_runtime/operator_shadow")).strip()
        or ".holo_runtime/operator_shadow",
        auto_observe=bool(memory_data.get("auto_observe", True)),
        promote_batch_size=int(memory_data.get("promote_batch_size", 8)),
        promote_interval_seconds=int(memory_data.get("promote_interval_seconds", 300)),
        maintenance_stream_interval_seconds=int(memory_data.get("maintenance_stream_interval_seconds", 300)),
        dream_interval_seconds=int(memory_data.get("dream_interval_seconds", 1800)),
        thought_interval_seconds=int(memory_data.get("thought_interval_seconds", 900)),
        reflection_interval_seconds=int(memory_data.get("reflection_interval_seconds", 1800)),
        initiative_interval_seconds=int(memory_data.get("initiative_interval_seconds", 1800)),
        association_stream_interval_seconds=int(memory_data.get("association_stream_interval_seconds", 900)),
        social_stream_interval_seconds=int(memory_data.get("social_stream_interval_seconds", 1800)),
        deep_dream_cycle_interval_seconds=int(memory_data.get("deep_dream_cycle_interval_seconds", 21600)),
        dream_sample_size=int(memory_data.get("dream_sample_size", 6)),
        thought_sample_size=int(memory_data.get("thought_sample_size", 4)),
        reflection_window_hours=float(memory_data.get("reflection_window_hours", 12.0)),
        history_messages=recall_history_messages,
        fast_history_messages=int(
            memory_data.get("fast_history_messages", runtime_data.get("fast_history_messages", 4))
        ),
        recall_history_messages=recall_history_messages,
        fast_episodic_k=int(memory_data.get("fast_episodic_k", 2)),
        recall_episodic_k=int(memory_data.get("recall_episodic_k", 4)),
        fast_consciousness_k=int(memory_data.get("fast_consciousness_k", 1)),
        recall_consciousness_k=int(memory_data.get("recall_consciousness_k", 2)),
        active_wechat_history_enabled=bool(memory_data.get("active_wechat_history_enabled", True)),
        active_wechat_history_limit=int(memory_data.get("active_wechat_history_limit", 40)),
        active_wechat_history_page_turns=int(memory_data.get("active_wechat_history_page_turns", 8)),
        active_wechat_history_cooldown_seconds=int(memory_data.get("active_wechat_history_cooldown_seconds", 180)),
        active_wechat_history_timeout_seconds=int(memory_data.get("active_wechat_history_timeout_seconds", 180)),
        active_wechat_history_deep_limit=int(memory_data.get("active_wechat_history_deep_limit", 120)),
        active_wechat_history_deep_page_turns=int(memory_data.get("active_wechat_history_deep_page_turns", 24)),
        active_wechat_history_deep_cooldown_seconds=int(memory_data.get("active_wechat_history_deep_cooldown_seconds", 15)),
        active_wechat_history_deep_timeout_seconds=int(memory_data.get("active_wechat_history_deep_timeout_seconds", 300)),
        active_wechat_history_include_visible=bool(memory_data.get("active_wechat_history_include_visible", True)),
        active_wechat_history_include_captures=bool(memory_data.get("active_wechat_history_include_captures", False)),
    )

    autonomy_data = data.get("autonomy", {})
    blocked_keywords = tuple(str(item) for item in autonomy_data.get("blocked_keywords", DEFAULT_BLOCKED_KEYWORDS))
    autonomy = AutonomyConfig(
        auto_send_mode=str(autonomy_data.get("auto_send_mode", "full_auto")),
        allow_proactive_existing_threads=bool(autonomy_data.get("allow_proactive_existing_threads", True)),
        allow_initiative_whitelist_contacts=bool(autonomy_data.get("allow_initiative_whitelist_contacts", True)),
        initiative_probe_enabled=bool(autonomy_data.get("initiative_probe_enabled", True)),
        game_state_enabled=bool(autonomy_data.get("game_state_enabled", True)),
        proactive_after_hours=int(autonomy_data.get("proactive_after_hours", 72)),
        initiative_cooldown_hours=int(autonomy_data.get("initiative_cooldown_hours", 48)),
        max_auto_replies_per_contact_per_hour=int(
            autonomy_data.get("max_auto_replies_per_contact_per_hour", 4)
        ),
        wechat_helper_config_path=str(autonomy_data.get("wechat_helper_config_path", "")),
        wechat_helper_windows_repo_root=str(autonomy_data.get("wechat_helper_windows_repo_root", "")),
        blocked_keywords=blocked_keywords,
    )

    ensure_directory(runtime.state_dir)
    ensure_directory(runtime.log_dir)
    ensure_directory(memory.mind_graph_db_path.parent)
    ensure_directory(mail.maildir_inbox)
    ensure_directory(mail.maildir_processed)
    ensure_directory(mail.maildir_outbox)
    return HostConfig(runtime=runtime, mail=mail, memory=memory, autonomy=autonomy, config_path=chosen_path)


def mail_password(config: HostConfig) -> str:
    if not config.mail.password_env:
        return ""
    return os.environ.get(config.mail.password_env, "")
