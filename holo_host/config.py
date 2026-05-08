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
class ProviderLaneConfig:
    primary_provider: str = "codex_cli"
    backup_provider: str = "responses"
    model: str = ""
    reasoning_effort: str = ""
    max_output_tokens: int = 0


@dataclass(slots=True)
class TaskRoutingConfig:
    lane: str = "subject_main"
    fallback_lane: str = ""
    budget_tag: str = ""
    upgrade_to_lane: str = ""
    uncertainty_threshold: float = 1.0
    high_conflict_actions: tuple[str, ...] = ()


@dataclass(slots=True)
class ProcessorFabricConfig:
    provider_backends: dict[str, ProviderLaneConfig] = field(default_factory=dict)
    processor_routing: dict[str, TaskRoutingConfig] = field(default_factory=dict)
    openai_compatible_base_url: str = ""
    openai_compatible_api_key_env: str = "OPENAI_COMPATIBLE_API_KEY"
    responses_api_key_env: str = "OPENAI_API_KEY"
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_api_key_env: str = "DEEPSEEK_API_KEY"
    deepseek_model: str = "deepseek-v4-pro"
    deepseek_fast_model: str = "deepseek-v4-flash"


# Backward-compatible alias for earlier imports and type hints.
ProcessorLaneConfig = ProviderLaneConfig


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
    autobiographical_consolidation_interval_seconds: int = 360
    goal_arbitration_interval_seconds: int = 420
    continuity_audit_interval_seconds: int = 300
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
    stage25_max_hot_threads_per_cycle: int = 6
    stage25_per_thread_pulse_budget: int = 2
    stage25_skip_cold_without_pressure: bool = True
    stage25_max_dense_working_set_threads: int = 8
    stage25_maintenance_stream_cooldown_seconds: int = 600
    stage25_association_stream_cooldown_seconds: int = 900
    stage25_social_stream_cooldown_seconds: int = 1200
    stage25_deep_dream_cycle_cooldown_seconds: int = 3600


@dataclass(slots=True)
class AutonomyConfig:
    auto_send_mode: str = "full_auto"
    allow_proactive_existing_threads: bool = True
    allow_initiative_whitelist_contacts: bool = True
    initiative_probe_enabled: bool = True
    initiative_gate_mode: str = "conservative"
    main_brain_override_enabled: bool = True
    main_brain_override_min_score: float = 0.58
    initiative_soft_allow_threshold: float = 0.62
    initiative_soft_override_floor: float = 0.48
    initiative_soft_trust_weight: float = 0.26
    initiative_soft_window_weight: float = 0.28
    initiative_soft_pressure_weight: float = 0.18
    initiative_soft_drive_weight: float = 0.28
    game_state_enabled: bool = True
    proactive_after_hours: int = 72
    initiative_cooldown_hours: int = 12
    max_auto_replies_per_contact_per_hour: int = 4
    wechat_helper_config_path: str = ""
    wechat_helper_windows_repo_root: str = ""
    stage22_canary_mode: str = "shadow"
    stage22_canary_whitelist_threads: tuple[str, ...] = ()
    stage22_canary_max_replies_per_thread_per_hour: int = 12
    stage22_canary_max_replies_global_per_hour: int = 30
    stage22_canary_artifact_capture: bool = True
    stage22_canary_artifact_root: str = "artifacts/canary/stage22"
    stage22_canary_rollback_file: str = ".holo_runtime/STAGE22_CANARY_ROLLBACK"
    blocked_keywords: tuple[str, ...] = field(default_factory=lambda: DEFAULT_BLOCKED_KEYWORDS)


@dataclass(slots=True)
class HostConfig:
    runtime: RuntimeConfig
    mail: MailConfig
    memory: MemoryConfig
    autonomy: AutonomyConfig
    processor_fabric: ProcessorFabricConfig
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


def _default_provider_backends(
    runtime: RuntimeConfig,
    processor_fabric_data: dict[str, Any] | None = None,
) -> dict[str, ProviderLaneConfig]:
    preferred = (runtime.processor_backend or "codex_cli").strip().lower()
    if preferred not in {"codex_cli", "responses", "openai_compatible", "deepseek"}:
        preferred = "codex_cli"
    if preferred == "codex_cli":
        subject_backup = "responses"
        kernel_backup = "responses"
        micro_backup = "responses"
    elif preferred == "responses":
        subject_backup = "codex_cli"
        kernel_backup = "codex_cli"
        micro_backup = "codex_cli"
    elif preferred == "openai_compatible":
        subject_backup = "responses"
        kernel_backup = "responses"
        micro_backup = "responses"
    else:
        subject_backup = "responses"
        kernel_backup = "responses"
        micro_backup = "responses"
    fabric = processor_fabric_data if isinstance(processor_fabric_data, dict) else {}
    main_model = str(fabric.get("deepseek_model", "deepseek-v4-pro")).strip() or "deepseek-v4-pro"
    fast_model = str(fabric.get("deepseek_fast_model", "deepseek-v4-flash")).strip() or "deepseek-v4-flash"
    default_main_model = main_model if preferred == "deepseek" else str(runtime.codex_model or runtime.responses_model or "gpt-5.4")
    default_fast_model = fast_model if preferred == "deepseek" else str(runtime.fast_model or runtime.responses_fast_model or "gpt-5.4-mini")
    return {
        "kernel_xhigh": ProviderLaneConfig(
            primary_provider=preferred,
            backup_provider=kernel_backup,
            model=default_main_model,
            reasoning_effort="xhigh",
            max_output_tokens=2400,
        ),
        "subject_main": ProviderLaneConfig(
            primary_provider=preferred,
            backup_provider=subject_backup,
            model=default_main_model,
            reasoning_effort="medium",
            max_output_tokens=1800,
        ),
        "micro_fast": ProviderLaneConfig(
            primary_provider=preferred,
            backup_provider=micro_backup,
            model=default_fast_model,
            reasoning_effort=str(runtime.fast_reasoning_effort or "low"),
            max_output_tokens=900,
        ),
    }


def _default_processor_routing() -> dict[str, TaskRoutingConfig]:
    return {
        "reply": TaskRoutingConfig(
            lane="subject_main",
            fallback_lane="micro_fast",
            budget_tag="chat_reply",
            upgrade_to_lane="kernel_xhigh",
            uncertainty_threshold=0.72,
            high_conflict_actions=("push_back", "counter_offer", "continuity_defense"),
        ),
        "recall_reconstruct": TaskRoutingConfig(lane="subject_main", fallback_lane="micro_fast", budget_tag="recall_reconstruct"),
        "goal_arbitration": TaskRoutingConfig(lane="subject_main", fallback_lane="micro_fast", budget_tag="goal_arbitration"),
        "autobiographical_consolidation": TaskRoutingConfig(lane="subject_main", fallback_lane="micro_fast", budget_tag="autobiographical_consolidation"),
        "world_calibration": TaskRoutingConfig(lane="subject_main", fallback_lane="micro_fast", budget_tag="world_calibration"),
        "image_understand": TaskRoutingConfig(lane="micro_fast", fallback_lane="subject_main", budget_tag="image_understand"),
        "self_model_observe": TaskRoutingConfig(lane="micro_fast", fallback_lane="subject_main", budget_tag="self_model_observe"),
        "initiative_probe": TaskRoutingConfig(lane="micro_fast", fallback_lane="subject_main", budget_tag="initiative_probe"),
        "affect_reflect": TaskRoutingConfig(lane="micro_fast", fallback_lane="subject_main", budget_tag="affect_reflect"),
        "drive_plan": TaskRoutingConfig(lane="micro_fast", fallback_lane="subject_main", budget_tag="drive_plan"),
        "value_integrate": TaskRoutingConfig(lane="micro_fast", fallback_lane="subject_main", budget_tag="value_integrate"),
        "conflict_arbitrate": TaskRoutingConfig(lane="micro_fast", fallback_lane="subject_main", budget_tag="conflict_arbitrate"),
        "outcome_appraise": TaskRoutingConfig(lane="micro_fast", fallback_lane="subject_main", budget_tag="outcome_appraise"),
        "deep_simulation": TaskRoutingConfig(lane="kernel_xhigh", fallback_lane="subject_main", budget_tag="deep_simulation"),
        "operator_plan": TaskRoutingConfig(lane="kernel_xhigh", fallback_lane="subject_main", budget_tag="operator_plan"),
        "operator_review": TaskRoutingConfig(lane="kernel_xhigh", fallback_lane="subject_main", budget_tag="operator_review"),
        "self_revision_plan": TaskRoutingConfig(lane="kernel_xhigh", fallback_lane="subject_main", budget_tag="self_revision_plan"),
        "self_revision_review": TaskRoutingConfig(lane="kernel_xhigh", fallback_lane="subject_main", budget_tag="self_revision_review"),
    }


def _load_provider_backends(
    raw: dict[str, Any],
    runtime: RuntimeConfig,
    processor_fabric_data: dict[str, Any] | None = None,
) -> dict[str, ProviderLaneConfig]:
    defaults = _default_provider_backends(runtime, processor_fabric_data)
    if not isinstance(raw, dict):
        return defaults
    resolved: dict[str, ProviderLaneConfig] = {}
    for lane_name, fallback in defaults.items():
        payload = raw.get(lane_name, {})
        if not isinstance(payload, dict):
            payload = {}
        resolved[lane_name] = ProviderLaneConfig(
            primary_provider=str(payload.get("primary_provider", fallback.primary_provider)).strip() or fallback.primary_provider,
            backup_provider=str(payload.get("backup_provider", fallback.backup_provider)).strip() or fallback.backup_provider,
            model=str(payload.get("model", fallback.model)).strip() or fallback.model,
            reasoning_effort=str(payload.get("reasoning_effort", fallback.reasoning_effort)).strip() or fallback.reasoning_effort,
            max_output_tokens=int(payload.get("max_output_tokens", fallback.max_output_tokens or 0)),
        )
    return resolved


def _load_processor_routing(raw: dict[str, Any]) -> dict[str, TaskRoutingConfig]:
    defaults = _default_processor_routing()
    if not isinstance(raw, dict):
        return defaults
    resolved: dict[str, TaskRoutingConfig] = {}
    for task_name, fallback in defaults.items():
        payload = raw.get(task_name, {})
        if not isinstance(payload, dict):
            payload = {}
        resolved[task_name] = TaskRoutingConfig(
            lane=str(payload.get("lane", fallback.lane)).strip() or fallback.lane,
            fallback_lane=str(payload.get("fallback_lane", fallback.fallback_lane)).strip() or fallback.fallback_lane,
            budget_tag=str(payload.get("budget_tag", fallback.budget_tag)).strip() or fallback.budget_tag,
            upgrade_to_lane=str(payload.get("upgrade_to_lane", fallback.upgrade_to_lane)).strip() or fallback.upgrade_to_lane,
            uncertainty_threshold=float(payload.get("uncertainty_threshold", fallback.uncertainty_threshold)),
            high_conflict_actions=tuple(
                str(item).strip()
                for item in payload.get("high_conflict_actions", fallback.high_conflict_actions)
                if str(item).strip()
            ),
        )
    for task_name, payload in raw.items():
        if task_name in resolved or not isinstance(payload, dict):
            continue
        resolved[task_name] = TaskRoutingConfig(
            lane=str(payload.get("lane", "subject_main")).strip() or "subject_main",
            fallback_lane=str(payload.get("fallback_lane", "")).strip(),
            budget_tag=str(payload.get("budget_tag", task_name)).strip() or task_name,
            upgrade_to_lane=str(payload.get("upgrade_to_lane", "")).strip(),
            uncertainty_threshold=float(payload.get("uncertainty_threshold", 1.0)),
            high_conflict_actions=tuple(str(item).strip() for item in payload.get("high_conflict_actions", []) if str(item).strip()),
        )
    return resolved


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
        autobiographical_consolidation_interval_seconds=int(memory_data.get("autobiographical_consolidation_interval_seconds", 360)),
        goal_arbitration_interval_seconds=int(memory_data.get("goal_arbitration_interval_seconds", 420)),
        continuity_audit_interval_seconds=int(memory_data.get("continuity_audit_interval_seconds", 300)),
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
        stage25_max_hot_threads_per_cycle=int(memory_data.get("stage25_max_hot_threads_per_cycle", 6)),
        stage25_per_thread_pulse_budget=int(memory_data.get("stage25_per_thread_pulse_budget", 2)),
        stage25_skip_cold_without_pressure=bool(memory_data.get("stage25_skip_cold_without_pressure", True)),
        stage25_max_dense_working_set_threads=int(memory_data.get("stage25_max_dense_working_set_threads", 8)),
        stage25_maintenance_stream_cooldown_seconds=int(memory_data.get("stage25_maintenance_stream_cooldown_seconds", 600)),
        stage25_association_stream_cooldown_seconds=int(memory_data.get("stage25_association_stream_cooldown_seconds", 900)),
        stage25_social_stream_cooldown_seconds=int(memory_data.get("stage25_social_stream_cooldown_seconds", 1200)),
        stage25_deep_dream_cycle_cooldown_seconds=int(memory_data.get("stage25_deep_dream_cycle_cooldown_seconds", 3600)),
    )

    autonomy_data = data.get("autonomy", {})
    blocked_keywords = tuple(str(item) for item in autonomy_data.get("blocked_keywords", DEFAULT_BLOCKED_KEYWORDS))
    autonomy = AutonomyConfig(
        auto_send_mode=str(autonomy_data.get("auto_send_mode", "full_auto")),
        allow_proactive_existing_threads=bool(autonomy_data.get("allow_proactive_existing_threads", True)),
        allow_initiative_whitelist_contacts=bool(autonomy_data.get("allow_initiative_whitelist_contacts", True)),
        initiative_probe_enabled=bool(autonomy_data.get("initiative_probe_enabled", True)),
        initiative_gate_mode=str(autonomy_data.get("initiative_gate_mode", "conservative") or "conservative"),
        main_brain_override_enabled=bool(autonomy_data.get("main_brain_override_enabled", True)),
        main_brain_override_min_score=float(autonomy_data.get("main_brain_override_min_score", 0.58) or 0.58),
        initiative_soft_allow_threshold=float(autonomy_data.get("initiative_soft_allow_threshold", 0.62) or 0.62),
        initiative_soft_override_floor=float(autonomy_data.get("initiative_soft_override_floor", 0.48) or 0.48),
        initiative_soft_trust_weight=float(autonomy_data.get("initiative_soft_trust_weight", 0.26) or 0.26),
        initiative_soft_window_weight=float(autonomy_data.get("initiative_soft_window_weight", 0.28) or 0.28),
        initiative_soft_pressure_weight=float(autonomy_data.get("initiative_soft_pressure_weight", 0.18) or 0.18),
        initiative_soft_drive_weight=float(autonomy_data.get("initiative_soft_drive_weight", 0.28) or 0.28),
        game_state_enabled=bool(autonomy_data.get("game_state_enabled", True)),
        proactive_after_hours=int(autonomy_data.get("proactive_after_hours", 72)),
        initiative_cooldown_hours=int(autonomy_data.get("initiative_cooldown_hours", 12)),
        max_auto_replies_per_contact_per_hour=int(
            autonomy_data.get("max_auto_replies_per_contact_per_hour", 4)
        ),
        wechat_helper_config_path=str(autonomy_data.get("wechat_helper_config_path", "")),
        wechat_helper_windows_repo_root=str(autonomy_data.get("wechat_helper_windows_repo_root", "")),
        stage22_canary_mode=str(autonomy_data.get("stage22_canary_mode", "shadow") or "shadow").strip().lower(),
        stage22_canary_whitelist_threads=tuple(
            str(item).strip()
            for item in autonomy_data.get("stage22_canary_whitelist_threads", [])
            if str(item).strip()
        ),
        stage22_canary_max_replies_per_thread_per_hour=int(
            autonomy_data.get("stage22_canary_max_replies_per_thread_per_hour", 12)
        ),
        stage22_canary_max_replies_global_per_hour=int(
            autonomy_data.get("stage22_canary_max_replies_global_per_hour", 30)
        ),
        stage22_canary_artifact_capture=bool(autonomy_data.get("stage22_canary_artifact_capture", True)),
        stage22_canary_artifact_root=str(
            autonomy_data.get("stage22_canary_artifact_root", "artifacts/canary/stage22")
        ).strip()
        or "artifacts/canary/stage22",
        stage22_canary_rollback_file=str(
            autonomy_data.get("stage22_canary_rollback_file", ".holo_runtime/STAGE22_CANARY_ROLLBACK")
        ).strip()
        or ".holo_runtime/STAGE22_CANARY_ROLLBACK",
        blocked_keywords=blocked_keywords,
    )

    processor_fabric_data = data.get("processor_fabric", {})
    processor_fabric = ProcessorFabricConfig(
        provider_backends=_load_provider_backends(data.get("provider_backends", {}), runtime, processor_fabric_data),
        processor_routing=_load_processor_routing(data.get("processor_routing", {})),
        openai_compatible_base_url=str(
            processor_fabric_data.get("openai_compatible_base_url", os.environ.get("OPENAI_COMPATIBLE_BASE_URL", ""))
        ).strip(),
        openai_compatible_api_key_env=str(
            processor_fabric_data.get("openai_compatible_api_key_env", "OPENAI_COMPATIBLE_API_KEY")
        ).strip()
        or "OPENAI_COMPATIBLE_API_KEY",
        responses_api_key_env=str(processor_fabric_data.get("responses_api_key_env", "OPENAI_API_KEY")).strip()
        or "OPENAI_API_KEY",
        deepseek_base_url=str(
            processor_fabric_data.get("deepseek_base_url", os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com"))
        ).strip()
        or "https://api.deepseek.com",
        deepseek_api_key_env=str(processor_fabric_data.get("deepseek_api_key_env", "DEEPSEEK_API_KEY")).strip()
        or "DEEPSEEK_API_KEY",
        deepseek_model=str(processor_fabric_data.get("deepseek_model", "deepseek-v4-pro")).strip()
        or "deepseek-v4-pro",
        deepseek_fast_model=str(processor_fabric_data.get("deepseek_fast_model", "deepseek-v4-flash")).strip()
        or "deepseek-v4-flash",
    )

    ensure_directory(runtime.state_dir)
    ensure_directory(runtime.log_dir)
    ensure_directory(memory.mind_graph_db_path.parent)
    ensure_directory(mail.maildir_inbox)
    ensure_directory(mail.maildir_processed)
    ensure_directory(mail.maildir_outbox)
    return HostConfig(
        runtime=runtime,
        mail=mail,
        memory=memory,
        autonomy=autonomy,
        processor_fabric=processor_fabric,
        config_path=chosen_path,
    )


def mail_password(config: HostConfig) -> str:
    if not config.mail.password_env:
        return ""
    return os.environ.get(config.mail.password_env, "")
