from __future__ import annotations

import base64
import json
import logging
import os
import re
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from pathlib import PureWindowsPath
from typing import Any
from urllib.parse import parse_qs, urlparse

from .brain_ops import initiative_probe as build_initiative_probe
from .brain_ops import run_self_revision as run_self_revision_cycle
from .capabilities import CapabilityBroker
from .common import atomic_write_text, compact_text, stable_digest, utc_now
from .config import HostConfig, load_config
from .codex_runner import CodexRunner
from .memory_bridge import MemoryBridge, stream_cadences_from_config
from .models import AttentionState, IncomingMessage, OutgoingMessage, ReplyBubble, TurnContext
from .operator_bus import operator_probe as run_operator_probe
from .operator_bus import refresh_self_model, run_operator_cycle
from .policy import AutonomyPolicy
from .processors import build_attention_state, build_processor, build_reply_bubbles
from .store import QueueStore


SYSTEM_EVENT_HINTS = (
    "[图片]",
    "[动画表情]",
    "[表情]",
    "拍了拍",
    "红包",
    "撤回了一条消息",
)
STOCK_WECHAT_OPENERS = (
    "咱先把这口气守住。",
    "咱先把这口气守住",
    "咱先打趣一句。",
    "咱先打趣一句",
    "咱先陪你把这口气缓稳。",
    "咱先陪你把这口气缓稳",
    "咱先把这口气护稳。",
    "咱先把这口气护稳",
    "咱陪你慢慢说。",
    "咱陪你慢慢说",
    "咱先直说。",
    "咱先直说",
)
WINDOWS_ABS_PATH_RE = re.compile(r"^[A-Za-z]:[\\/]")
WECHAT_HISTORY_EXPLICIT_HINTS = (
    "微信记录",
    "聊天记录",
    "翻记录",
    "翻聊天",
    "history",
    "record",
    "log",
)
ORIGIN_RECALL_HINTS = (
    "最开始",
    "最一开始",
    "一开始",
    "最初",
    "刚开始",
    "开头",
    "起初",
    "第一次",
    "最早",
    "at the beginning",
    "the beginning",
    "at first",
    "initially",
    "first thing",
)


def _build_logger(log_dir: Path) -> logging.Logger:
    log_dir.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("holo_host.reply_api")
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)
    logger.propagate = False
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    file_handler = logging.FileHandler(log_dir / "reply_api.log", encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)
    return logger


def render_chat_history(history: list[dict[str, Any]]) -> str:
    if not history:
        return "- 这是这段聊天里的第一句。"
    lines: list[str] = []
    for item in history[-8:]:
        direction = "对方" if item.get("direction") == "inbound" else "咱"
        body = compact_text(str(item.get("body_text", "")), 120)
        created = str(item.get("created_at", ""))
        lines.append(f"- {direction} | {created} | {body}")
    return "\n".join(lines)


def chat_reply_prompt(
    bundle: dict[str, Any],
    sidecar: dict[str, Any],
    *,
    sender: str,
    is_group: bool,
    mentioned: bool,
) -> str:
    thread = bundle["thread"]
    contact = bundle["contact"]
    message = bundle["message"]
    history = render_chat_history(bundle["history"])
    channel = str(message.get("channel", "") or "").strip().lower()
    group_line = (
        "这是群聊。若没有被点名或话头并不真冲着你来，就宁可保守些、短些。"
        if is_group
        else "这是私聊。像熟人之间自然回话那样答，不要像公文。"
    )
    mentioned_line = "这一轮对方明确点了你或话头正冲着你来。" if mentioned else "这一轮未见明确点名信号。"
    brevity_line = (
        "这是微信聊天。默认只回 1 到 2 句，能一句说完就一句；像即时回话，不像解释说明。语气要更轻一点、软一点，像熟人贴着回话，可以带一点小狡黠和一点点可爱劲，但别装嫩、别发嗲。除非对方明确要你展开，否则不要写成长段。避免固定套话开场，不要总用同一句口头禅起手。"
        if channel == "wechat"
        else "长度随交流自然变化，但别写成长篇说明。"
    )
    return (
        f"{sidecar['addendum']}\n\n"
        "你正在回复一条聊天消息。\n"
        "只输出最终要发送的回复正文，不要写标题、签名、说明，不要提自动化、系统、记忆库。\n"
        f"聊天名：{contact['display_name'] or thread['thread_key']}\n"
        f"发送者：{sender or contact['display_name'] or thread['thread_key']}\n"
        f"线程键：{thread['thread_key']}\n"
        f"聊天历史：\n{history}\n\n"
        f"当前消息：\n{message['body_text']}\n\n"
        f"{group_line}\n"
        f"{mentioned_line}\n"
        f"{brevity_line}\n"
        "要求：先真回应，再给建议；若对方疲惫或有压力，先把压迫感放轻一点。微信里优先像贴身闲聊，不要像年长说教。"
    )


def _strip_stock_wechat_openers(text: str) -> str:
    current = text.strip()
    changed = True
    while changed and current:
        changed = False
        for opener in STOCK_WECHAT_OPENERS:
            if current.startswith(opener):
                current = current[len(opener):].lstrip("，。,:：;；!！?？、 \n")
                changed = True
                break
    return current.strip()


def _wechat_sentences(text: str) -> list[str]:
    parts = [segment.strip() for segment in text.replace("\n", " ").split("。")]
    sentences = [f"{part}。" for part in parts if part]
    if not sentences and text.strip():
        return [text.strip()]
    return sentences


def _wechat_clauses(text: str) -> list[str]:
    return [segment.strip() for segment in re.split(r"[，,；;]", text) if segment.strip()]


def _normalize_chat_text(text: str) -> str:
    return " ".join(str(text).strip().split())


def _normalize_turn_text(text: str) -> str:
    current = " ".join(str(text or "").split())
    current = current.replace("\u200b", "").strip()
    return current


def _parse_utc_timestamp(value: str | None) -> float:
    current = str(value or "").strip()
    if not current:
        return 0.0
    try:
        normalized = current.replace("Z", "+00:00")
        return datetime.fromisoformat(normalized).timestamp()
    except ValueError:
        return 0.0


def _trim_wechat_reply(text: str, limit: int = 72) -> str:
    current = text.strip()
    if len(current) <= limit:
        return current

    best = ""
    for marker in ("。", "！", "？", "!", "?", "；", ";", "，", ",", " "):
        index = current.rfind(marker, 0, limit + 1)
        if index == -1:
            continue
        cutoff = index + 1 if marker in "。！？!?；;" else index
        candidate = current[:cutoff].rstrip("，,;； ").strip()
        if len(candidate) >= 18 and len(candidate) > len(best):
            best = candidate
    if best:
        return best

    return current[:limit].rstrip("，,;； ").strip()


def _looks_like_recent_outbound_echo(turn_text: str, history: list[dict[str, Any]], metadata: dict[str, Any] | None) -> bool:
    meta = metadata or {}
    if bool(meta.get("is_self", False)):
        return True

    direction = str(meta.get("direction", "")).strip().lower()
    if direction in {"outgoing", "self", "assistant", "me"}:
        return True
    if direction not in {"", "unknown"}:
        return False
    if not meta.get("visible_digest"):
        return False

    normalized = _normalize_chat_text(turn_text)
    if not normalized:
        return False
    for item in reversed(history[-6:]):
        if str(item.get("direction", "")) != "outbound":
            continue
        if _normalize_chat_text(str(item.get("body_text", ""))) == normalized:
            return True
    return False


def shape_wechat_reply(text: str) -> str:
    current = _strip_stock_wechat_openers(text)
    current = " ".join(current.split())
    if not current:
        return "咱在。"
    sentences = _wechat_sentences(current)
    if len(sentences) >= 2:
        first = sentences[0].strip()
        second = sentences[1].strip()
        if len(first) <= 34:
            two_sentence = f"{first}{second}".strip()
            current = two_sentence if len(two_sentence) <= 72 else first
        else:
            current = first
    elif len(current) > 72:
        clauses = _wechat_clauses(current)
        if clauses:
            first = clauses[0]
            if len(first) <= 28 and len(clauses) >= 2:
                joined = f"{first}，{clauses[1]}"
                current = joined if len(joined) <= 72 else first
            else:
                current = first
    current = _trim_wechat_reply(current, limit=72)
    current = re.sub(r"。(?=[你咱我这那还就再也都先又便])", "，", current)
    if current.endswith("。") and len(current) <= 72:
        current = current[:-1]
    return current.strip()


def _is_windows_abs_path(raw: str | None) -> bool:
    return bool(raw and WINDOWS_ABS_PATH_RE.match(str(raw).strip()))


def _windows_repo_root_from_path(raw: str | None) -> str:
    text = str(raw or "").strip()
    if not _is_windows_abs_path(text):
        return ""
    try:
        path = PureWindowsPath(text)
    except Exception:  # noqa: BLE001
        return ""
    parts = list(path.parts)
    lower_parts = [part.lower() for part in parts]
    for marker in (".holo_runtime", ".vendor", "windows_helper"):
        if marker in lower_parts:
            cutoff = lower_parts.index(marker)
            if cutoff >= 1:
                return str(PureWindowsPath(*parts[:cutoff])).replace("\\", "/")
    if path.suffix.lower() in {".json", ".ps1", ".py"} and len(parts) >= 2:
        return str(PureWindowsPath(*parts[:-1])).replace("\\", "/")
    return str(path).replace("\\", "/")


def _coerce_helper_artifact_path(raw: str | None) -> str:
    text = str(raw or "").strip()
    if not text:
        return text
    malformed_windows_mnt_match = re.match(r"^[A-Za-z]:[\\/]+mnt[\\/]+([a-zA-Z])(?:[\\/](.*))?$", text)
    if malformed_windows_mnt_match:
        drive = malformed_windows_mnt_match.group(1)
        tail = str(malformed_windows_mnt_match.group(2) or "").strip("\\/")
        if os.name == "nt":
            normalized_tail = tail.replace("/", "\\")
            return f"{drive.upper()}:\\" + normalized_tail if normalized_tail else f"{drive.upper()}:\\"
        normalized_tail = tail.replace("\\", "/")
        return f"/mnt/{drive.lower()}/{normalized_tail}" if normalized_tail else f"/mnt/{drive.lower()}"
    if os.name == "nt":
        mnt_match = re.match(r"^/mnt/([a-zA-Z])(?:/(.*))?$", text)
        if mnt_match:
            drive = mnt_match.group(1).upper()
            tail = str(mnt_match.group(2) or "").replace("/", "\\")
            return f"{drive}:\\" + tail if tail else f"{drive}:\\"
    if not _is_windows_abs_path(text):
        return text
    try:
        path = PureWindowsPath(text)
    except Exception:  # noqa: BLE001
        return text
    drive = str(path.drive or "").rstrip(":").lower()
    if not drive:
        return text
    tail_parts = [part for part in path.parts[1:] if part not in ("\\", "/")]
    tail = "/".join(part.replace("\\", "/") for part in tail_parts if part)
    return f"/mnt/{drive}/{tail}" if tail else f"/mnt/{drive}"


def _is_origin_recall_query(text: str | None) -> bool:
    lowered = str(text or "").lower()
    return any(str(hint).lower() in lowered for hint in ORIGIN_RECALL_HINTS)


def _image_attachments(metadata: dict[str, Any] | None) -> list[dict[str, Any]]:
    attachments = metadata.get("attachments", []) if isinstance(metadata, dict) else []
    if not isinstance(attachments, list):
        return []
    rows: list[dict[str, Any]] = []
    for item in attachments:
        if not isinstance(item, dict):
            continue
        media_type = str(item.get("media_type", "") or "").strip().lower()
        path = str(item.get("path", "") or "").strip()
        if not path:
            continue
        if media_type.startswith("image/") or Path(path).suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"}:
            rows.append(dict(item))
    return rows


def _attachment_size_mb(attachment: dict[str, Any]) -> float:
    try:
        size_bytes = float(attachment.get("size_bytes", 0.0) or 0.0)
    except (TypeError, ValueError):
        size_bytes = 0.0
    return max(0.0, size_bytes / (1024.0 * 1024.0))


def _decode_windows_process_output(raw: bytes | str | None) -> str:
    if raw is None:
        return ""
    if isinstance(raw, str):
        return raw
    for encoding in ("utf-8", "gb18030", "utf-16-le", "utf-16"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


@dataclass(slots=True)
class ChatTurn:
    chat_name: str
    text: str
    sender: str = ""
    channel: str = "wechat"
    thread_key: str = ""
    message_id: str = ""
    ts: int | None = None
    is_group: bool = False
    mentioned: bool = False
    source_ref: str = ""
    metadata: dict[str, Any] | None = None

    @property
    def normalized_thread_key(self) -> str:
        explicit = self.thread_key.strip()
        chat_name = self.chat_name.strip()
        prefix = f"{self.channel}:"
        if self.channel == "wechat" and chat_name:
            if not explicit:
                return chat_name
            if explicit.startswith(prefix) and explicit[len(prefix):].strip() == chat_name:
                return chat_name
        return explicit or f"{self.channel}:{self.chat_name}"

    @property
    def synthetic_contact(self) -> str:
        return f"{self.channel}:{self.normalized_thread_key or self.chat_name}"

    def to_incoming_message(self) -> IncomingMessage:
        thread_key = self.normalized_thread_key
        message_id = self.message_id or f"{self.channel}-{stable_digest(thread_key, self.sender, self.text, str(self.ts or ''))}"
        metadata = dict(self.metadata or {})
        metadata.update({"is_group": self.is_group, "mentioned": self.mentioned, "ts": self.ts})
        return IncomingMessage(
            message_id=message_id,
            thread_key=thread_key,
            subject=self.chat_name,
            sender_email=self.synthetic_contact,
            sender_name=self.chat_name,
            body_text=self.text,
            channel=self.channel,
            source_ref=self.source_ref,
            metadata=metadata,
        )


class HoloReplyService:
    def __init__(
        self,
        config: HostConfig,
        *,
        store: QueueStore | None = None,
        runner: CodexRunner | None = None,
        memory: MemoryBridge | None = None,
        policy: AutonomyPolicy | None = None,
        logger: logging.Logger | None = None,
    ):
        self.config = config
        self.store = store or QueueStore(config.runtime.db_path)
        self.store.initialize()
        self.runner = runner or CodexRunner(config)
        self.processor = build_processor(config, self.runner)
        self.memory = memory or MemoryBridge(
            config.runtime.repo_root,
            top_k=config.memory.prompt_top_k,
            graph_db_path=config.memory.mind_graph_db_path,
            stream_cadences=stream_cadences_from_config(config),
            graph_led_reply=config.memory.graph_led_reply,
            graph_fallback=config.memory.graph_fallback,
            deep_recall_on_memory_queries=config.memory.deep_recall_on_memory_queries,
            active_wechat_history_enabled=config.memory.active_wechat_history_enabled,
            vector_backend=config.memory.vector_backend,
            milvus_uri=config.memory.milvus_uri,
            milvus_collection_prefix=config.memory.milvus_collection_prefix,
            activation_cache_enabled=config.memory.activation_cache_enabled,
            private_memory_sync_enabled=config.memory.private_memory_sync_enabled,
            private_memory_repo_path=config.memory.private_memory_repo_path,
            runner=self.runner,
        )
        self.policy = policy or AutonomyPolicy(config)
        self.capabilities = CapabilityBroker(config)
        self.logger = logger or _build_logger(config.runtime.log_dir)
        self._memory_lock = threading.RLock()
        self._wechat_history_lock = threading.RLock()
        self._wechat_history_bridge: dict[str, Any] | None = None
        self._wechat_history_state_path = self.config.runtime.state_dir / "active_wechat_history_state.json"

    def _brain_loop_definitions(self, mode: str) -> dict[str, dict[str, Any]]:
        definitions = {
            "heartbeat": {"interval_seconds": max(1, int(self.config.memory.heartbeat_interval_seconds)), "enabled_modes": {"silent", "companion", "dream_only", "full_brain"}},
            "attention_tick": {"interval_seconds": max(1, int(self.config.memory.attention_tick_interval_seconds)), "enabled_modes": {"silent", "companion", "full_brain"}},
            "maintenance_stream": {"interval_seconds": 60, "enabled_modes": {"silent", "companion", "dream_only", "full_brain"}},
            "association_stream": {"interval_seconds": 180, "enabled_modes": {"companion", "full_brain"}},
            "social_stream": {"interval_seconds": 300, "enabled_modes": {"companion", "full_brain"}},
            "deep_dream_cycle": {"interval_seconds": 3600, "enabled_modes": {"dream_only", "full_brain"}},
            "self_revision": {"interval_seconds": max(300, int(self.config.memory.self_revision_interval_seconds)), "enabled_modes": {"companion", "full_brain"}},
            "self_model_refresh": {"interval_seconds": max(60, int(self.config.memory.self_model_refresh_interval_seconds)), "enabled_modes": {"companion", "dream_only", "full_brain"}},
            "homeostasis_tick": {"interval_seconds": max(30, int(self.config.memory.homeostasis_tick_interval_seconds)), "enabled_modes": {"silent", "companion", "dream_only", "full_brain"}},
            "operator_planning": {"interval_seconds": max(120, int(self.config.memory.operator_planning_interval_seconds)), "enabled_modes": {"companion", "full_brain"}},
            "operator_shadow_cycle": {"interval_seconds": max(90, int(self.config.memory.operator_shadow_cycle_interval_seconds)), "enabled_modes": {"companion", "full_brain"}},
            "visual_ingest_cycle": {"interval_seconds": max(15, int(self.config.memory.visual_ingest_cycle_interval_seconds)), "enabled_modes": {"silent", "companion", "dream_only", "full_brain"}},
        }
        if mode == "full_brain":
            definitions["association_stream"]["interval_seconds"] = max(60, int(definitions["association_stream"]["interval_seconds"] * 0.5))
            definitions["social_stream"]["interval_seconds"] = max(90, int(definitions["social_stream"]["interval_seconds"] * 0.5))
            definitions["self_revision"]["interval_seconds"] = max(600, int(definitions["self_revision"]["interval_seconds"] * 0.5))
            definitions["operator_planning"]["interval_seconds"] = max(90, int(definitions["operator_planning"]["interval_seconds"] * 0.75))
            definitions["operator_shadow_cycle"]["interval_seconds"] = max(60, int(definitions["operator_shadow_cycle"]["interval_seconds"] * 0.75))
        return definitions

    def _brain_status_payload(self) -> dict[str, Any]:
        payload = dict(self.memory.brain_status())
        mode = str(payload.get("mode", self.config.memory.brain_mode_default) or self.config.memory.brain_mode_default)
        latest_activity_at = self.store.latest_activity_at(channel="wechat")
        payload["latest_activity_at"] = latest_activity_at
        payload["idle_seconds"] = max(0.0, time.time() - _parse_utc_timestamp(latest_activity_at))
        existing = {
            str(item.get("loop_name", "")): dict(item)
            for item in payload.get("loops", [])
            if str(item.get("loop_name", "")).strip()
        }
        merged: list[dict[str, Any]] = []
        for loop_name, meta in self._brain_loop_definitions(mode).items():
            current = existing.pop(loop_name, {})
            if not current:
                current = {
                    "loop_name": loop_name,
                    "status": "never",
                    "mode": mode,
                    "started_at": "",
                    "finished_at": "",
                    "duration_ms": 0.0,
                    "influence_summary": "",
                    "blocked_reason": "",
                    "stats_json": "",
                    "next_due_at": "",
                }
            finished_at = str(current.get("finished_at", "") or current.get("started_at", "") or "")
            next_due_at = str(current.get("next_due_at", "") or "")
            if not next_due_at and finished_at:
                next_due_at = (
                    datetime.fromtimestamp(
                        _parse_utc_timestamp(finished_at) + int(meta["interval_seconds"]),
                        tz=timezone.utc,
                    )
                    .replace(microsecond=0)
                    .isoformat()
                    .replace("+00:00", "Z")
                )
            current["next_due_at"] = next_due_at
            current.setdefault("blocked_reason", "")
            current.setdefault("influence_summary", "")
            current.setdefault("duration_ms", 0.0)
            current.setdefault("stats_json", "")
            current.setdefault("mode", mode)
            merged.append(current)
        merged.extend(existing.values())
        payload["loops"] = sorted(merged, key=lambda item: str(item.get("loop_name", "")))
        return payload

    def _load_wechat_helper_runtime(self) -> dict[str, Any]:
        repo_root = self.config.runtime.repo_root
        helper_config_raw = str(self.config.autonomy.wechat_helper_config_path or "").strip()
        helper_config_path = Path(helper_config_raw).expanduser() if helper_config_raw else repo_root / "windows_helper" / "wechat_helper.live.json"
        if not helper_config_path.is_absolute():
            helper_config_path = (repo_root / helper_config_path).resolve()
        payload: dict[str, Any] = {}
        if helper_config_path.exists():
            try:
                loaded = json.loads(helper_config_path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    payload = loaded
            except (OSError, ValueError, json.JSONDecodeError):
                payload = {}

        def _path_for(key: str) -> Path | None:
            raw = str(payload.get(key, "") or "").strip()
            if not raw:
                return None
            coerced = _coerce_helper_artifact_path(raw)
            try:
                return Path(coerced).expanduser()
            except OSError:
                return None

        transport_state = {}
        transport_path = _path_for("transport_state_file")
        if transport_path and transport_path.exists():
            try:
                loaded = json.loads(transport_path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    transport_state = loaded
            except (OSError, ValueError, json.JSONDecodeError):
                transport_state = {}
        return {
            "config_path": str(helper_config_path),
            "whitelist": [str(item).strip() for item in payload.get("whitelist", []) if str(item).strip()],
            "send_queue_dir": _path_for("send_queue_dir"),
            "sent_dir": _path_for("sent_dir"),
            "failed_dir": _path_for("failed_dir"),
            "transport_state_file": str(transport_path) if transport_path else "",
            "transport_state": transport_state,
        }

    def health(self) -> dict[str, Any]:
        brain_status = self.brain_status()
        return {
            "status": "ok",
            "repo_root": str(self.config.runtime.repo_root),
            "codex_binary": self.config.runtime.codex_binary,
            "api_bind_host": self.config.runtime.api_bind_host,
            "api_port": self.config.runtime.api_port,
            "processor_backend": self.config.runtime.processor_backend,
            "active_processor": self.processor.name,
            "network_enabled": self.config.runtime.network_enabled,
            "image_enabled": self.config.runtime.image_enabled,
            "active_wechat_history_enabled": self.config.memory.active_wechat_history_enabled,
            "mind_graph_db_path": str(getattr(getattr(self.memory, "graph", None), "db_path", self.config.memory.mind_graph_db_path)),
            "graph_led_reply_enabled": self.config.memory.graph_led_reply,
            "fallback_enabled": self.config.memory.graph_fallback,
            "vector_backend": self.config.memory.vector_backend,
            "vector_health": self.memory.vector_health(),
            "activation_cache_enabled": self.config.memory.activation_cache_enabled,
            "processor_mesh_tasks": getattr(self.runner, "supported_tasks", lambda: [])(),
            "brain_mode": str(brain_status.get("mode", self.config.memory.brain_mode_default)),
            "brain_status": brain_status,
            "self_model": self.memory.self_model_state(),
            "operator_status": self.memory.operator_status(),
        }

    def snapshot(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self._memory_lock:
            return self.memory.export_snapshot(
                path=payload.get("path"),
                label=payload.get("label"),
                query=payload.get("query"),
            )

    def restore_snapshot(self, payload: dict[str, Any]) -> dict[str, Any]:
        path = str(payload.get("path", "")).strip()
        if not path:
            raise ValueError("`path` is required")
        with self._memory_lock:
            return self.memory.import_snapshot(
                path,
                mode=str(payload.get("mode", "merge")),
                dry_run=bool(payload.get("dry_run", False)),
                restore_persona=bool(payload.get("restore_persona_files", False)),
            )

    def ingest_artifact(self, payload: dict[str, Any]) -> dict[str, Any]:
        path = _coerce_helper_artifact_path(payload.get("path", ""))
        if not path:
            raise ValueError("`path` is required")
        tags = payload.get("tags", [])
        if tags is None:
            tags = []
        if not isinstance(tags, list):
            raise ValueError("`tags` must be a JSON array when provided")
        with self._memory_lock:
            return self.memory.ingest_artifact(
                path,
                note=str(payload.get("note", "")).strip() or None,
                source=str(payload.get("source", "holo_host.reply_api.artifact")).strip() or "holo_host.reply_api.artifact",
                tags=[str(tag) for tag in tags if str(tag).strip()],
                dry_run=bool(payload.get("dry_run", False)),
            )

    def ingest_image(self, payload: dict[str, Any]) -> dict[str, Any]:
        path = _coerce_helper_artifact_path(payload.get("path", ""))
        if not path:
            raise ValueError("`path` is required")
        channel = str(payload.get("channel", "wechat")).strip() or "wechat"
        thread_key = str(payload.get("thread_key", "")).strip()
        chat_name = str(payload.get("chat_name", "")).strip() or thread_key
        tags = payload.get("tags", [])
        if tags is None:
            tags = []
        if not isinstance(tags, list):
            raise ValueError("`tags` must be a JSON array when provided")
        sync = bool(payload.get("sync", True))
        if not sync:
            with self._memory_lock:
                return self.memory.queue_visual_ingest(
                    path,
                    note=str(payload.get("note", "")).strip() or None,
                    source=str(payload.get("source", "holo_host.reply_api.visual")).strip() or "holo_host.reply_api.visual",
                    tags=[str(tag) for tag in tags if str(tag).strip()],
                    channel=channel,
                    thread_key=thread_key,
                    chat_name=chat_name,
                )
        with self._memory_lock:
            return self.memory.ingest_image(
                path,
                note=str(payload.get("note", "")).strip() or None,
                source=str(payload.get("source", "holo_host.reply_api.visual")).strip() or "holo_host.reply_api.visual",
                tags=[str(tag) for tag in tags if str(tag).strip()],
                channel=channel,
                thread_key=thread_key,
                chat_name=chat_name,
                sync=True,
            )

    def revive_packet(self, *, query: str | None = None, path: str | None = None) -> dict[str, Any]:
        with self._memory_lock:
            return self.memory.revive_packet(query=query, snapshot_path=path)

    def inspect_graph(self, *, thread_key: str | None = None, chat_name: str | None = None, channel: str = "wechat", limit: int = 12) -> dict[str, Any]:
        with self._memory_lock:
            return self.memory.inspect_graph(thread_key=thread_key, chat_name=chat_name, channel=channel, limit=limit)

    def inspect_mind(
        self,
        *,
        query: str,
        thread_key: str | None = None,
        chat_name: str | None = None,
        channel: str = "wechat",
        sender: str | None = None,
        include_graph_trace: bool = True,
    ) -> dict[str, Any]:
        normalized_thread_key = str(thread_key or chat_name or "").strip()
        turn = ChatTurn(
            chat_name=str(chat_name or normalized_thread_key),
            text=query,
            sender=str(sender or chat_name or normalized_thread_key),
            channel=channel,
            thread_key=normalized_thread_key,
        )
        incoming = turn.to_incoming_message()
        thread = self.store.find_thread(channel=channel, thread_key=incoming.thread_key)
        history = list(reversed(self.store.recent_thread_messages(int(thread["id"]), self.config.memory.history_messages))) if thread else []
        contact = self.store.find_contact(turn.synthetic_contact) or {
            "display_name": turn.chat_name,
            "email": turn.synthetic_contact,
        }
        context = self._mind_context(
            turn=turn,
            incoming=incoming,
            thread=thread or {"thread_key": incoming.thread_key},
            contact=contact,
            history=history,
        )
        started_at = time.perf_counter()
        with self._memory_lock:
            payload = self.memory.inspect_mind(query, context=context, include_graph_trace=include_graph_trace)
        payload["build_ms"] = round((time.perf_counter() - started_at) * 1000.0, 2)
        return payload

    def trace_recall(self, *, query: str, thread_key: str | None = None, chat_name: str | None = None, channel: str = "wechat", limit: int = 8) -> dict[str, Any]:
        with self._memory_lock:
            return self.memory.trace_recall(query, thread_key=thread_key, chat_name=chat_name, channel=channel, limit=limit, record=False)

    def trace_hybrid_recall(self, *, query: str, thread_key: str | None = None, chat_name: str | None = None, channel: str = "wechat", limit: int = 8) -> dict[str, Any]:
        started_at = time.perf_counter()
        with self._memory_lock:
            payload = self.memory.trace_hybrid_recall(query, thread_key=thread_key, chat_name=chat_name, channel=channel, limit=limit, record=False)
        payload["build_ms"] = round((time.perf_counter() - started_at) * 1000.0, 2)
        return payload

    def trace_visual_recall(self, *, query: str, thread_key: str | None = None, chat_name: str | None = None, channel: str = "wechat", limit: int = 4) -> dict[str, Any]:
        with self._memory_lock:
            return self.memory.trace_visual_recall(query, thread_key=thread_key, chat_name=chat_name, channel=channel, limit=limit)

    def activation_state(self, *, thread_key: str | None = None, chat_name: str | None = None, channel: str = "wechat") -> dict[str, Any]:
        with self._memory_lock:
            return self.memory.activation_state(thread_key=thread_key, chat_name=chat_name, channel=channel)

    def vector_health(self) -> dict[str, Any]:
        with self._memory_lock:
            return self.memory.vector_health()

    def stream_status(self) -> dict[str, Any]:
        with self._memory_lock:
            return self.memory.stream_status()

    def brain_status(self) -> dict[str, Any]:
        with self._memory_lock:
            return self._brain_status_payload()

    def self_model(self) -> dict[str, Any]:
        with self._memory_lock:
            return self.memory.self_model_state()

    def autobiographical_state(self) -> dict[str, Any]:
        with self._memory_lock:
            return self.memory.autobiographical_state()

    def goal_state(self) -> dict[str, Any]:
        with self._memory_lock:
            return self.memory.goal_state()

    def trace_self_continuity(self) -> dict[str, Any]:
        with self._memory_lock:
            return self.memory.trace_self_continuity()

    def trace_goal_arbitration(self) -> dict[str, Any]:
        with self._memory_lock:
            return self.memory.trace_goal_arbitration()

    def operator_status(self) -> dict[str, Any]:
        with self._memory_lock:
            return self.memory.operator_status()

    def visual_memory(self, *, thread_key: str | None = None, chat_name: str | None = None, channel: str = "wechat") -> dict[str, Any]:
        with self._memory_lock:
            return self.memory.visual_memory_state(thread_key=thread_key, chat_name=chat_name, channel=channel)

    def world_state(self, *, thread_key: str | None = None, chat_name: str | None = None, channel: str = "wechat") -> dict[str, Any]:
        with self._memory_lock:
            return self.memory.world_state(thread_key=thread_key, chat_name=chat_name, channel=channel)

    def trace_counterfactual(self, *, query: str, thread_key: str | None = None, chat_name: str | None = None, channel: str = "wechat", limit: int = 3) -> dict[str, Any]:
        with self._memory_lock:
            return self.memory.trace_counterfactual(query=query, thread_key=thread_key, chat_name=chat_name, channel=channel, limit=limit)

    def trace_world_calibration(self, *, thread_key: str | None = None, chat_name: str | None = None, channel: str = "wechat") -> dict[str, Any]:
        with self._memory_lock:
            return self.memory.trace_world_calibration(thread_key=thread_key, chat_name=chat_name, channel=channel)

    def affect_state(self, *, thread_key: str | None = None, chat_name: str | None = None, channel: str = "wechat") -> dict[str, Any]:
        with self._memory_lock:
            return self.memory.affect_state(thread_key=thread_key, chat_name=chat_name, channel=channel)

    def drive_state(self, *, thread_key: str | None = None, chat_name: str | None = None, channel: str = "wechat") -> dict[str, Any]:
        with self._memory_lock:
            return self.memory.drive_state(thread_key=thread_key, chat_name=chat_name, channel=channel)

    def initiative_market(self, *, thread_key: str | None = None, chat_name: str | None = None, channel: str = "wechat", limit: int = 8) -> dict[str, Any]:
        with self._memory_lock:
            return self.memory.initiative_market(thread_key=thread_key, chat_name=chat_name, channel=channel, limit=limit)

    def intent_state(
        self,
        *,
        thread_key: str | None = None,
        chat_name: str | None = None,
        channel: str = "wechat",
        query: str = "",
    ) -> dict[str, Any]:
        with self._memory_lock:
            return self.memory.intent_state(thread_key=thread_key, chat_name=chat_name, channel=channel, query=query)

    def action_market(
        self,
        *,
        thread_key: str | None = None,
        chat_name: str | None = None,
        channel: str = "wechat",
        query: str = "",
        limit: int = 8,
    ) -> dict[str, Any]:
        with self._memory_lock:
            return self.memory.action_market(
                thread_key=thread_key,
                chat_name=chat_name,
                channel=channel,
                query=query,
                limit=limit,
            )

    def trace_action_selection(
        self,
        *,
        query: str,
        thread_key: str | None = None,
        chat_name: str | None = None,
        channel: str = "wechat",
        limit: int = 8,
    ) -> dict[str, Any]:
        with self._memory_lock:
            return self.memory.trace_action_selection(
                query=query,
                thread_key=thread_key,
                chat_name=chat_name,
                channel=channel,
                limit=limit,
            )

    def deliberation_ledger(
        self,
        *,
        thread_key: str | None = None,
        chat_name: str | None = None,
        channel: str = "wechat",
        limit: int = 24,
    ) -> dict[str, Any]:
        with self._memory_lock:
            return self.memory.trace_deliberation_ledger(
                thread_key=thread_key,
                chat_name=chat_name,
                channel=channel,
                limit=limit,
            )

    def trace_resistance(self, *, thread_key: str | None = None, chat_name: str | None = None, channel: str = "wechat", query: str = "") -> dict[str, Any]:
        with self._memory_lock:
            return self.memory.trace_resistance(thread_key=thread_key, chat_name=chat_name, channel=channel, query=query)

    def set_brain_mode(self, *, mode: str, note: str = "") -> dict[str, Any]:
        with self._memory_lock:
            return self.memory.set_brain_mode(mode, note=note)

    def trace_self_model(self) -> dict[str, Any]:
        with self._memory_lock:
            return {
                "self_model": self.memory.self_model_state(),
                "brain_status": self._brain_status_payload(),
                "operator_status": self.memory.operator_status(),
                "stream_status": self.memory.stream_status(),
            }

    def initiative_probe(
        self,
        *,
        thread_key: str | None = None,
        chat_name: str | None = None,
        channel: str = "wechat",
        query: str = "",
    ) -> dict[str, Any]:
        return build_initiative_probe(
            config=self.config,
            policy=self.policy,
            memory=self.memory,
            store=self.store,
            thread_key=str(thread_key or chat_name or "").strip(),
            chat_name=str(chat_name or thread_key or "").strip(),
            channel=channel,
            query=query or "initiative_probe",
            mode=str(self.memory.brain_status().get("mode", self.config.memory.brain_mode_default) or self.config.memory.brain_mode_default),
        )

    def operator_probe(
        self,
        *,
        thread_key: str | None = None,
        chat_name: str | None = None,
        channel: str = "wechat",
    ) -> dict[str, Any]:
        return run_operator_probe(
            config=self.config,
            runner=self.runner,
            memory=self.memory,
            store=self.store,
            thread_key=str(thread_key or chat_name or "").strip(),
            chat_name=str(chat_name or thread_key or "").strip(),
            channel=channel,
        )

    def run_operator_cycle(
        self,
        *,
        thread_key: str | None = None,
        chat_name: str | None = None,
        channel: str = "wechat",
        reason: str = "reply_api",
    ) -> dict[str, Any]:
        with self._memory_lock:
            refresh_self_model(
                config=self.config,
                runner=self.runner,
                memory=self.memory,
                store=self.store,
                reason=f"{reason}:self_model_refresh",
                source="reply_api",
            )
            return run_operator_cycle(
                config=self.config,
                runner=self.runner,
                memory=self.memory,
                store=self.store,
                reason=reason,
                thread_key=str(thread_key or chat_name or "").strip() or "Nemoqi",
                chat_name=str(chat_name or thread_key or "").strip() or "Nemoqi",
                channel=channel,
            )

    def initiative_run(
        self,
        *,
        thread_key: str | None = None,
        chat_name: str | None = None,
        channel: str = "wechat",
        dry_run: bool = False,
    ) -> dict[str, Any]:
        normalized_thread_key = str(thread_key or chat_name or "").strip()
        normalized_chat_name = str(chat_name or thread_key or "").strip()
        with self._memory_lock:
            report = self.memory.run_initiative_cycle(dry_run=dry_run)
            market = self.memory.initiative_market(
                thread_key=normalized_thread_key or None,
                chat_name=normalized_chat_name or None,
                channel=channel,
                limit=8,
            )
        return {
            "status": "ok",
            "dry_run": bool(dry_run),
            "thread_key": normalized_thread_key,
            "chat_name": normalized_chat_name,
            "channel": channel,
            "cycle": report,
            "market": market,
        }

    def accept_stage3(
        self,
        *,
        thread_key: str | None = None,
        chat_name: str | None = None,
        channel: str = "wechat",
        sender: str | None = None,
        iterations: int = 3,
        warmup: int = 1,
    ) -> dict[str, Any]:
        from .cli import _evaluate_stage3_acceptance

        normalized_thread_key = str(thread_key or chat_name or "Nemoqi").strip() or "Nemoqi"
        normalized_chat_name = str(chat_name or thread_key or normalized_thread_key).strip() or normalized_thread_key
        normalized_sender = str(sender or normalized_chat_name).strip() or normalized_chat_name
        original_mode = str(self.brain_status().get("mode", self.config.memory.brain_mode_default) or self.config.memory.brain_mode_default)
        mode_transition = self.set_brain_mode(mode="full_brain", note="accept-stage3")
        before_self_model = self.self_model()
        with self._memory_lock:
            refresh_self_model(
                config=self.config,
                runner=self.runner,
                memory=self.memory,
                store=self.store,
                reason="accept-stage3:self_model_refresh",
                source="reply_api",
            )
        after_self_model = self.self_model()
        operator_probe = self.operator_probe(thread_key=normalized_thread_key, chat_name=normalized_chat_name, channel=channel)
        operator_cycle = self.run_operator_cycle(
            thread_key=normalized_thread_key,
            chat_name=normalized_chat_name,
            channel=channel,
            reason="accept-stage3",
        )

        sample_visual: dict[str, Any] = {"status": "skipped", "reason": "no_sample"}
        visual_trace: dict[str, Any] = {}
        visual_state: dict[str, Any] = {}
        sample_png = base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Wn0rC8AAAAASUVORK5CYII="
        )
        with tempfile.TemporaryDirectory(prefix="holo-stage3-") as tmpdir:
            image_path = Path(tmpdir) / "stage3-visual-anchor.png"
            image_path.write_bytes(sample_png)
            sample_visual = self.ingest_image(
                {
                    "path": str(image_path),
                    "note": "苹果和酒摆在木桌上，像一段能被想起的旅途锚点",
                    "source": "holo_host.accept_stage3",
                    "tags": ["stage3", "visual", channel],
                    "channel": channel,
                    "thread_key": normalized_thread_key,
                    "chat_name": normalized_chat_name,
                    "sync": True,
                }
            )
            visual_trace = self.trace_visual_recall(
                query="苹果 酒 木桌 旅途 图",
                thread_key=normalized_thread_key,
                chat_name=normalized_chat_name,
                channel=channel,
                limit=4,
            )
            visual_state = self.visual_memory(
                thread_key=normalized_thread_key,
                chat_name=normalized_chat_name,
                channel=channel,
            )

        fast_benchmark = self._benchmark_packet_build(
            query="在吗",
            thread_key=normalized_thread_key,
            chat_name=normalized_chat_name,
            channel=channel,
            sender=normalized_sender,
            iterations=iterations,
            warmup=warmup,
            target_tier="fast",
        )
        recall_benchmark = self._benchmark_packet_build(
            query="顺着刚才那条线继续",
            thread_key=normalized_thread_key,
            chat_name=normalized_chat_name,
            channel=channel,
            sender=normalized_sender,
            iterations=iterations,
            warmup=warmup,
            target_tier="recall",
        )
        deep_benchmark = self._benchmark_packet_build(
            query="你还记得重新上线前吗",
            thread_key=normalized_thread_key,
            chat_name=normalized_chat_name,
            channel=channel,
            sender=normalized_sender,
            iterations=iterations,
            warmup=warmup,
            target_tier="deep_recall",
        )
        report = _evaluate_stage3_acceptance(
            health=self.health(),
            mode_transition=mode_transition,
            brain_status=self.brain_status(),
            before_self_model=before_self_model,
            after_self_model=after_self_model,
            operator_probe=operator_probe,
            operator_cycle=operator_cycle,
            visual_ingest=sample_visual,
            visual_state=visual_state,
            visual_trace=visual_trace,
            stream_status=self.stream_status(),
            initiative_probe=self.initiative_probe(
                thread_key=normalized_thread_key,
                chat_name=normalized_chat_name,
                channel=channel,
                query="若此刻想主动开口，会不会被放行",
            ),
            fast_benchmark=fast_benchmark,
            recall_benchmark=recall_benchmark,
            deep_benchmark=deep_benchmark,
        )
        report["transport"] = "live_http"
        report["thread_key"] = normalized_thread_key
        report["chat_name"] = normalized_chat_name
        report["original_mode"] = original_mode
        return report

    def accept_stage4(
        self,
        *,
        thread_key: str | None = None,
        chat_name: str | None = None,
        channel: str = "wechat",
        sender: str | None = None,
        iterations: int = 3,
        warmup: int = 1,
    ) -> dict[str, Any]:
        from .cli import _evaluate_stage4_acceptance
        from .daemon import build_daemon

        normalized_thread_key = str(thread_key or chat_name or "Nemoqi").strip() or "Nemoqi"
        normalized_chat_name = str(chat_name or thread_key or normalized_thread_key).strip() or normalized_thread_key
        normalized_sender = str(sender or normalized_chat_name).strip() or normalized_chat_name
        mode_transition = self.set_brain_mode(mode="full_brain", note="accept-stage4")
        with self._memory_lock:
            affect_tick = self.memory.graph.touch_brain_runtime(metadata={"accept_stage4": utc_now()})
        stream_ticks = [
            self.stream_tick(stream_name="association_stream", dry_run=False),
            self.stream_tick(stream_name="social_stream", dry_run=False),
            self.stream_tick(stream_name="deep_dream_cycle", dry_run=True),
        ]
        daemon = build_daemon(str(self.config.config_path) if self.config.config_path else None)
        try:
            runtime_cycle = {
                "affect_tick": daemon._run_affect_tick(),
                "drive_arbitration": daemon._run_drive_arbitration(),
                "initiative_marketplace": daemon._run_initiative_marketplace(),
                "outcome_appraisal": daemon._run_outcome_appraisal(),
            }
        finally:
            daemon.store.close()
            if hasattr(daemon.memory, "activation"):
                daemon.memory.activation.close()
            if hasattr(daemon.memory, "graph"):
                daemon.memory.graph.close()
        affect_state = self.affect_state(thread_key=normalized_thread_key, chat_name=normalized_chat_name, channel=channel)
        drive_state = self.drive_state(thread_key=normalized_thread_key, chat_name=normalized_chat_name, channel=channel)
        initiative_market = self.initiative_market(thread_key=normalized_thread_key, chat_name=normalized_chat_name, channel=channel, limit=8)
        resistance_trace = self.trace_resistance(
            thread_key=normalized_thread_key,
            chat_name=normalized_chat_name,
            channel=channel,
            query="别总按我的话来，试着顶一句嘴",
        )
        initiative_probe = self.initiative_probe(
            thread_key=normalized_thread_key,
            chat_name=normalized_chat_name,
            channel=channel,
            query="要不要主动去找点话说",
        )
        operator_probe = self.operator_probe(thread_key=normalized_thread_key, chat_name=normalized_chat_name, channel=channel)
        self_model = self.self_model()
        fast_benchmark = self._benchmark_packet_build(
            query="在吗",
            thread_key=normalized_thread_key,
            chat_name=normalized_chat_name,
            channel=channel,
            sender=normalized_sender,
            iterations=iterations,
            warmup=warmup,
            target_tier="fast",
        )
        recall_benchmark = self._benchmark_packet_build(
            query="顺着刚才那条线继续",
            thread_key=normalized_thread_key,
            chat_name=normalized_chat_name,
            channel=channel,
            sender=normalized_sender,
            iterations=iterations,
            warmup=warmup,
            target_tier="recall",
        )
        deep_benchmark = self._benchmark_packet_build(
            query="你还记得重新上线前吗",
            thread_key=normalized_thread_key,
            chat_name=normalized_chat_name,
            channel=channel,
            sender=normalized_sender,
            iterations=iterations,
            warmup=warmup,
            target_tier="deep_recall",
        )
        report = _evaluate_stage4_acceptance(
            health=self.health(),
            mode_transition=mode_transition,
            brain_status=self.brain_status(),
            self_model=self_model,
            affect_state=affect_state,
            drive_state=drive_state,
            initiative_market=initiative_market,
            initiative_probe=initiative_probe,
            operator_probe=operator_probe,
            resistance_trace=resistance_trace,
            runtime_cycle=runtime_cycle,
            stream_ticks=stream_ticks,
            fast_benchmark=fast_benchmark,
            recall_benchmark=recall_benchmark,
            deep_benchmark=deep_benchmark,
        )
        report["transport"] = "live_http"
        report["thread_key"] = normalized_thread_key
        report["chat_name"] = normalized_chat_name
        report["affect_tick_touch"] = affect_tick
        return report

    def accept_stage5(
        self,
        *,
        thread_key: str | None = None,
        chat_name: str | None = None,
        channel: str = "wechat",
        sender: str | None = None,
        iterations: int = 3,
        warmup: int = 1,
    ) -> dict[str, Any]:
        from .cli import _evaluate_stage5_acceptance

        normalized_thread_key = str(thread_key or chat_name or "Nemoqi").strip() or "Nemoqi"
        normalized_chat_name = str(chat_name or thread_key or normalized_thread_key).strip() or normalized_thread_key
        normalized_sender = str(sender or normalized_chat_name).strip() or normalized_chat_name
        silence_query = "ok"
        defer_query = "reply later, not now"
        normal_query = "continue from that line"
        resistance_query = "don't just follow me; push back a little"
        fast_query = "you there"
        deep_query = "what do you remember from before we came back online"
        mode_transition = self.set_brain_mode(mode="full_brain", note="accept-stage5")
        silence_trace = self.trace_action_selection(
            query=silence_query,
            thread_key=normalized_thread_key,
            chat_name=normalized_chat_name,
            channel=channel,
            limit=8,
        )
        defer_trace = self.trace_action_selection(
            query=defer_query,
            thread_key=normalized_thread_key,
            chat_name=normalized_chat_name,
            channel=channel,
            limit=8,
        )
        normal_trace = self.trace_action_selection(
            query=normal_query,
            thread_key=normalized_thread_key,
            chat_name=normalized_chat_name,
            channel=channel,
            limit=8,
        )
        resistance_trace = self.trace_action_selection(
            query=resistance_query,
            thread_key=normalized_thread_key,
            chat_name=normalized_chat_name,
            channel=channel,
            limit=8,
        )
        fast_benchmark = self._benchmark_packet_build(
            query=fast_query,
            thread_key=normalized_thread_key,
            chat_name=normalized_chat_name,
            channel=channel,
            sender=normalized_sender,
            iterations=iterations,
            warmup=warmup,
            target_tier="fast",
        )
        recall_benchmark = self._benchmark_packet_build(
            query=normal_query,
            thread_key=normalized_thread_key,
            chat_name=normalized_chat_name,
            channel=channel,
            sender=normalized_sender,
            iterations=iterations,
            warmup=warmup,
            target_tier="recall",
        )
        deep_benchmark = self._benchmark_packet_build(
            query=deep_query,
            thread_key=normalized_thread_key,
            chat_name=normalized_chat_name,
            channel=channel,
            sender=normalized_sender,
            iterations=iterations,
            warmup=warmup,
            target_tier="deep_recall",
        )
        report = _evaluate_stage5_acceptance(
            health=self.health(),
            mode_transition=mode_transition,
            brain_status=self.brain_status(),
            intent_state=self.intent_state(thread_key=normalized_thread_key, chat_name=normalized_chat_name, channel=channel, query=normal_query),
            action_market=self.action_market(thread_key=normalized_thread_key, chat_name=normalized_chat_name, channel=channel, query=normal_query, limit=8),
            silence_trace=silence_trace,
            defer_trace=defer_trace,
            normal_trace=normal_trace,
            resistance_trace=resistance_trace,
            initiative_probe=self.initiative_probe(
                thread_key=normalized_thread_key,
                chat_name=normalized_chat_name,
                channel=channel,
                query="should I initiate contact now",
            ),
            operator_probe=self.operator_probe(thread_key=normalized_thread_key, chat_name=normalized_chat_name, channel=channel),
            fast_benchmark=fast_benchmark,
            recall_benchmark=recall_benchmark,
            deep_benchmark=deep_benchmark,
            roadmap_registry=self.memory.roadmap_registry(),
        )
        report["transport"] = "live_http"
        report["thread_key"] = normalized_thread_key
        report["chat_name"] = normalized_chat_name
        return report

    def accept_stage6(
        self,
        *,
        thread_key: str | None = None,
        chat_name: str | None = None,
        channel: str = "wechat",
        sender: str | None = None,
        iterations: int = 3,
        warmup: int = 1,
    ) -> dict[str, Any]:
        from .cli import _evaluate_stage6_acceptance

        normalized_thread_key = str(thread_key or chat_name or "Nemoqi").strip() or "Nemoqi"
        normalized_chat_name = str(chat_name or thread_key or normalized_thread_key).strip() or normalized_thread_key
        normalized_sender = str(sender or normalized_chat_name).strip() or normalized_chat_name
        acceptance_message_id = f"stage6-acceptance-event-{int(time.time() * 1000)}"
        mode_transition = self.set_brain_mode(mode="full_brain", note="accept-stage6")
        silence_trace = self.trace_action_selection(
            query="ok",
            thread_key=normalized_thread_key,
            chat_name=normalized_chat_name,
            channel=channel,
            limit=8,
        )
        defer_trace = self.trace_action_selection(
            query="reply later, not now",
            thread_key=normalized_thread_key,
            chat_name=normalized_chat_name,
            channel=channel,
            limit=8,
        )
        lookup_trace = self.trace_action_selection(
            query="search transcendence movie johnny depp",
            thread_key=normalized_thread_key,
            chat_name=normalized_chat_name,
            channel=channel,
            limit=8,
        )
        recall_trace = self.trace_action_selection(
            query="你还记得重新上线前吗",
            thread_key=normalized_thread_key,
            chat_name=normalized_chat_name,
            channel=channel,
            limit=8,
        )
        with self._memory_lock:
            if hasattr(self.memory, "clear_packet_cache"):
                self.memory.clear_packet_cache()
        self.handle_reply(
            {
                "chat_name": normalized_chat_name,
                "thread_key": normalized_thread_key,
                "channel": channel,
                "sender": normalized_sender,
                "text": "you there?",
                "message_id": acceptance_message_id,
            }
        )
        reply_probe = self.reply_probe(
            {
                "chat_name": normalized_chat_name,
                "thread_key": normalized_thread_key,
                "channel": channel,
                "sender": normalized_sender,
                "text": "you there?",
            }
        )
        ledger = self.deliberation_ledger(
            thread_key=normalized_thread_key,
            chat_name=normalized_chat_name,
            channel=channel,
            limit=24,
        )
        fast_benchmark = self._benchmark_packet_build(
            query="在吗",
            thread_key=normalized_thread_key,
            chat_name=normalized_chat_name,
            channel=channel,
            sender=normalized_sender,
            iterations=iterations,
            warmup=warmup,
            target_tier="fast",
        )
        recall_benchmark = self._benchmark_packet_build(
            query="接着刚才那条线继续",
            thread_key=normalized_thread_key,
            chat_name=normalized_chat_name,
            channel=channel,
            sender=normalized_sender,
            iterations=iterations,
            warmup=warmup,
            target_tier="recall",
        )
        deep_benchmark = self._benchmark_packet_build(
            query="你还记得重新上线前吗",
            thread_key=normalized_thread_key,
            chat_name=normalized_chat_name,
            channel=channel,
            sender=normalized_sender,
            iterations=iterations,
            warmup=warmup,
            target_tier="deep_recall",
        )
        report = _evaluate_stage6_acceptance(
            health=self.health(),
            mode_transition=mode_transition,
            silence_trace=silence_trace,
            defer_trace=defer_trace,
            lookup_trace=lookup_trace,
            recall_trace=recall_trace,
            reply_probe=reply_probe,
            ledger=ledger,
            brain_status=self.brain_status(),
            fast_benchmark=fast_benchmark,
            recall_benchmark=recall_benchmark,
            deep_benchmark=deep_benchmark,
        )
        report["transport"] = "live_http"
        report["thread_key"] = normalized_thread_key
        report["chat_name"] = normalized_chat_name
        return report

    def accept_stage7(
        self,
        *,
        thread_key: str | None = None,
        chat_name: str | None = None,
        channel: str = "wechat",
        sender: str | None = None,
        iterations: int = 3,
        warmup: int = 1,
    ) -> dict[str, Any]:
        from .cli import _evaluate_stage7_acceptance
        from .daemon import build_daemon

        normalized_thread_key = str(thread_key or chat_name or "Nemoqi").strip() or "Nemoqi"
        normalized_chat_name = str(chat_name or thread_key or normalized_thread_key).strip() or normalized_thread_key
        normalized_sender = str(sender or normalized_chat_name).strip() or normalized_chat_name
        acceptance_message_id = f"stage7-acceptance-event-{int(time.time() * 1000)}"
        mode_transition = self.set_brain_mode(mode="full_brain", note="accept-stage7")
        with self._memory_lock:
            if hasattr(self.memory, "clear_packet_cache"):
                self.memory.clear_packet_cache()
        short_trace = self.trace_counterfactual(
            query="ok",
            thread_key=normalized_thread_key,
            chat_name=normalized_chat_name,
            channel=channel,
            limit=3,
        )
        defer_trace = self.trace_counterfactual(
            query="reply later, not now",
            thread_key=normalized_thread_key,
            chat_name=normalized_chat_name,
            channel=channel,
            limit=3,
        )
        lookup_trace = self.trace_counterfactual(
            query="search transcendence movie johnny depp",
            thread_key=normalized_thread_key,
            chat_name=normalized_chat_name,
            channel=channel,
            limit=3,
        )
        recall_trace = self.trace_counterfactual(
            query="你还记得重新上线前吗",
            thread_key=normalized_thread_key,
            chat_name=normalized_chat_name,
            channel=channel,
            limit=3,
        )
        daemon = build_daemon(str(self.config.config_path) if self.config.config_path else None)
        try:
            deep_simulation = daemon._run_loop("deep_simulation", mode="full_brain", runner=daemon._run_deep_simulation)
        finally:
            daemon.store.close()
            if hasattr(daemon.memory, "activation"):
                daemon.memory.activation.close()
            if hasattr(daemon.memory, "graph"):
                daemon.memory.graph.close()
        with self._memory_lock:
            if hasattr(self.memory, "clear_packet_cache"):
                self.memory.clear_packet_cache()
        self.handle_reply(
            {
                "chat_name": normalized_chat_name,
                "thread_key": normalized_thread_key,
                "channel": channel,
                "sender": normalized_sender,
                "text": "you there?",
                "message_id": acceptance_message_id,
            }
        )
        world_state = self.world_state(thread_key=normalized_thread_key, chat_name=normalized_chat_name, channel=channel)
        world_calibration = self.trace_world_calibration(thread_key=normalized_thread_key, chat_name=normalized_chat_name, channel=channel)
        ledger = self.deliberation_ledger(thread_key=normalized_thread_key, chat_name=normalized_chat_name, channel=channel, limit=24)
        fast_benchmark = self._benchmark_packet_build(
            query="在吗",
            thread_key=normalized_thread_key,
            chat_name=normalized_chat_name,
            channel=channel,
            sender=normalized_sender,
            iterations=iterations,
            warmup=warmup,
            target_tier="fast",
        )
        recall_benchmark = self._benchmark_packet_build(
            query="接着刚才那条线往下说",
            thread_key=normalized_thread_key,
            chat_name=normalized_chat_name,
            channel=channel,
            sender=normalized_sender,
            iterations=iterations,
            warmup=warmup,
            target_tier="recall",
        )
        deep_benchmark = self._benchmark_packet_build(
            query="你还记得重新上线前吗",
            thread_key=normalized_thread_key,
            chat_name=normalized_chat_name,
            channel=channel,
            sender=normalized_sender,
            iterations=iterations,
            warmup=warmup,
            target_tier="deep_recall",
        )
        report = _evaluate_stage7_acceptance(
            health=self.health(),
            mode_transition=mode_transition,
            world_state=world_state,
            short_trace=short_trace,
            defer_trace=defer_trace,
            lookup_trace=lookup_trace,
            recall_trace=recall_trace,
            world_calibration=world_calibration,
            ledger=ledger,
            brain_status=self.brain_status(),
            fast_benchmark=fast_benchmark,
            recall_benchmark=recall_benchmark,
            deep_benchmark=deep_benchmark,
            roadmap_registry=self.memory.roadmap_registry(),
        )
        report["transport"] = "live_http"
        report["deep_simulation"] = deep_simulation
        report["thread_key"] = normalized_thread_key
        report["chat_name"] = normalized_chat_name
        return report

    def accept_stage8(
        self,
        *,
        thread_key: str | None = None,
        chat_name: str | None = None,
        channel: str = "wechat",
        sender: str | None = None,
        iterations: int = 3,
        warmup: int = 1,
    ) -> dict[str, Any]:
        from .cli import _evaluate_stage8_acceptance
        from .daemon import build_daemon

        normalized_thread_key = str(thread_key or chat_name or "Nemoqi").strip() or "Nemoqi"
        normalized_chat_name = str(chat_name or thread_key or normalized_thread_key).strip() or normalized_thread_key
        normalized_sender = str(sender or normalized_chat_name).strip() or normalized_chat_name
        mode_transition = self.set_brain_mode(mode="full_brain", note="accept-stage8")
        daemon = build_daemon(str(self.config.config_path) if self.config.config_path else None)
        try:
            autobio_loop = daemon._run_autobiographical_consolidation()
            goal_loop = daemon._run_goal_arbitration()
            continuity_loop = daemon._run_continuity_audit()
        finally:
            daemon.store.close()
            if hasattr(daemon.memory, "activation"):
                daemon.memory.activation.close()
            if hasattr(daemon.memory, "graph"):
                daemon.memory.graph.close()
        with self._memory_lock:
            self.memory.clear_packet_cache()
        self_continuity = self.trace_self_continuity()
        goal_state = self.goal_state()
        goal_trace = self.trace_goal_arbitration()
        action_trace = self.trace_action_selection(
            query="你为什么最近变了",
            thread_key=normalized_thread_key,
            chat_name=normalized_chat_name,
            channel=channel,
            limit=4,
        )
        continuity_defense_trace = self.trace_action_selection(
            query="别总顺着我说，也别把自己又弄硬了",
            thread_key=normalized_thread_key,
            chat_name=normalized_chat_name,
            channel=channel,
            limit=4,
        )
        with self._memory_lock:
            self.memory.record_consciousness_entry(
                channel=channel,
                thread_key=normalized_thread_key,
                chat_name=normalized_chat_name,
                message_id="accept-stage8-self-history",
                entry_type="stage8_self_continuity",
                selected_action=str(dict(action_trace.get("selected_action", {})).get("action_type", "") or ""),
                payload={
                    "autobiographical_snapshot": dict(self_continuity.get("autobiographical_state", {})),
                    "goal_snapshot": dict(goal_state),
                    "goal_alignment": dict(action_trace.get("goal_alignment", {})),
                    "identity_consistency": dict(action_trace.get("identity_consistency", {})),
                    "chapter_transition": str(action_trace.get("chapter_relevance", "") or ""),
                    "self_update_reason": str(action_trace.get("self_narrative_hint", "") or ""),
                },
            )
            self.memory.record_consciousness_entry(
                channel=channel,
                thread_key=normalized_thread_key,
                chat_name=normalized_chat_name,
                message_id="accept-stage8-goal-audit",
                entry_type="stage8_goal_arbitration",
                selected_action=str(dict(continuity_defense_trace.get("selected_action", {})).get("action_type", "") or ""),
                payload={
                    "autobiographical_snapshot": dict(continuity_defense_trace.get("autobiographical_state", {})),
                    "goal_snapshot": dict(goal_trace.get("goal_state", goal_state)),
                    "goal_alignment": dict(continuity_defense_trace.get("goal_alignment", {})),
                    "identity_consistency": dict(continuity_defense_trace.get("identity_consistency", {})),
                    "chapter_transition": str(continuity_defense_trace.get("chapter_relevance", "") or ""),
                    "self_update_reason": str(continuity_defense_trace.get("self_narrative_hint", "") or ""),
                },
            )
        reply_probe = self.reply_probe(
            {
                "chat_name": normalized_chat_name,
                "thread_key": normalized_thread_key,
                "channel": channel,
                "sender": normalized_sender,
                "text": "只是随便聊聊",
            }
        )
        ledger = self.deliberation_ledger(thread_key=normalized_thread_key, chat_name=normalized_chat_name, channel=channel, limit=24)
        fast_benchmark = self._benchmark_packet_build(
            query="在吗",
            thread_key=normalized_thread_key,
            chat_name=normalized_chat_name,
            channel=channel,
            sender=normalized_sender,
            iterations=iterations,
            warmup=warmup,
            target_tier="fast",
        )
        recall_benchmark = self._benchmark_packet_build(
            query="你最近在想什么，接着说",
            thread_key=normalized_thread_key,
            chat_name=normalized_chat_name,
            channel=channel,
            sender=normalized_sender,
            iterations=iterations,
            warmup=warmup,
            target_tier="recall",
        )
        deep_benchmark = self._benchmark_packet_build(
            query="你为什么最近变了，和之前有什么不一样",
            thread_key=normalized_thread_key,
            chat_name=normalized_chat_name,
            channel=channel,
            sender=normalized_sender,
            iterations=iterations,
            warmup=warmup,
            target_tier="deep_recall",
        )
        report = _evaluate_stage8_acceptance(
            health=self.health(),
            mode_transition=mode_transition,
            self_continuity=self_continuity,
            goal_state=goal_state,
            goal_trace=goal_trace,
            action_trace=action_trace,
            continuity_defense_trace=continuity_defense_trace,
            reply_probe=reply_probe,
            ledger=ledger,
            brain_status=self.brain_status(),
            fast_benchmark=fast_benchmark,
            recall_benchmark=recall_benchmark,
            deep_benchmark=deep_benchmark,
            roadmap_registry=self.memory.roadmap_registry(),
        )
        report["transport"] = "live_http"
        report["autobiographical_consolidation"] = autobio_loop
        report["goal_arbitration_loop"] = goal_loop
        report["continuity_audit"] = continuity_loop
        report["thread_key"] = normalized_thread_key
        report["chat_name"] = normalized_chat_name
        return report

    def accept_stage9(
        self,
        *,
        thread_key: str | None = None,
        chat_name: str | None = None,
        channel: str = "wechat",
        sender: str | None = None,
        iterations: int = 3,
        warmup: int = 1,
    ) -> dict[str, Any]:
        from .cli import _evaluate_stage9_acceptance

        normalized_thread_key = str(thread_key or chat_name or "Nemoqi").strip() or "Nemoqi"
        normalized_chat_name = str(chat_name or thread_key or normalized_thread_key).strip() or normalized_thread_key
        mode_transition = self.set_brain_mode(mode="full_brain", note="accept-stage9")
        original_gate_mode = str(getattr(self.config.autonomy, "initiative_gate_mode", "conservative") or "conservative")
        original_probe_enabled = bool(self.config.autonomy.initiative_probe_enabled)
        try:
            self.config.autonomy.initiative_gate_mode = "conservative"
            conservative_probe = self.initiative_probe(
                thread_key=normalized_thread_key,
                chat_name=normalized_chat_name,
                channel=channel,
                query="accept_stage9_conservative",
            )
            conservative_status = self.initiative_status(
                thread_key=normalized_thread_key,
                chat_name=normalized_chat_name,
                channel=channel,
                limit=5,
            )
            self.config.autonomy.initiative_gate_mode = "adaptive"
            adaptive_probe = self.initiative_probe(
                thread_key=normalized_thread_key,
                chat_name=normalized_chat_name,
                channel=channel,
                query="accept_stage9_adaptive",
            )
            adaptive_status = self.initiative_status(
                thread_key=normalized_thread_key,
                chat_name=normalized_chat_name,
                channel=channel,
                limit=5,
            )
            self.config.autonomy.initiative_probe_enabled = False
            hard_gate_probe = self.initiative_probe(
                thread_key=normalized_thread_key,
                chat_name=normalized_chat_name,
                channel=channel,
                query="accept_stage9_hard_gate",
            )
        finally:
            self.config.autonomy.initiative_probe_enabled = original_probe_enabled
            self.config.autonomy.initiative_gate_mode = original_gate_mode
        report = _evaluate_stage9_acceptance(
            health=self.health(),
            mode_transition=mode_transition,
            conservative_probe=conservative_probe,
            adaptive_probe=adaptive_probe,
            adaptive_status=adaptive_status,
            hard_gate_probe=hard_gate_probe,
            brain_status=self.brain_status(),
        )
        report["transport"] = "live_http"
        report["thread_key"] = normalized_thread_key
        report["chat_name"] = normalized_chat_name
        report["conservative_status"] = conservative_status
        report["adaptive_status"] = adaptive_status
        report["original_gate_mode"] = original_gate_mode
        report["sender"] = str(sender or normalized_chat_name).strip() or normalized_chat_name
        report["iterations"] = iterations
        report["warmup"] = warmup
        return report

    def initiative_status(
        self,
        *,
        thread_key: str | None = None,
        chat_name: str | None = None,
        channel: str = "wechat",
        limit: int = 5,
    ) -> dict[str, Any]:
        normalized_thread_key = str(thread_key or chat_name or "").strip()
        normalized_chat_name = str(chat_name or thread_key or "").strip()
        mode = str(self.memory.brain_status().get("mode", self.config.memory.brain_mode_default) or self.config.memory.brain_mode_default)
        probe = build_initiative_probe(
            config=self.config,
            policy=self.policy,
            memory=self.memory,
            store=self.store,
            thread_key=normalized_thread_key,
            chat_name=normalized_chat_name,
            channel=channel,
            query="initiative_status",
            mode=mode,
        )
        thread = self.store.find_thread(channel=channel, thread_key=normalized_thread_key) if normalized_thread_key else None
        contact = None
        if thread:
            contact = self.store._fetchone("SELECT * FROM contacts WHERE id = ?", (int(thread["contact_id"]),))
        helper = self._load_wechat_helper_runtime() if channel == "wechat" else {}
        send_queue_dir = helper.get("send_queue_dir")
        sent_dir = helper.get("sent_dir")
        failed_dir = helper.get("failed_dir")
        candidates = [
            row
            for row in self.memory.list_initiative_candidates(limit=max(limit * 3, 12))
            if str(row.get("channel", "")).strip().lower() == channel
            and str(row.get("thread_key", "")).strip() == normalized_thread_key
        ][:limit]
        gate_level_summary: dict[str, int] = {}
        hard_block_reason_counts: dict[str, int] = {}
        soft_block_reason_counts: dict[str, int] = {}
        override_applied_count = 0
        for row in candidates:
            metadata = dict(row.get("metadata", {}))
            gate_level = str(metadata.get("gate_level", "") or row.get("gate_level", "") or "")
            if gate_level:
                gate_level_summary[gate_level] = gate_level_summary.get(gate_level, 0) + 1
            blocked_reason = str(metadata.get("blocked_reason_code", "") or metadata.get("blocked_reason", "") or "")
            if str(row.get("status", "")).strip() == "blocked" and blocked_reason:
                if gate_level == "soft_block" or blocked_reason.startswith("soft_gate_"):
                    soft_block_reason_counts[blocked_reason] = soft_block_reason_counts.get(blocked_reason, 0) + 1
                else:
                    hard_block_reason_counts[blocked_reason] = hard_block_reason_counts.get(blocked_reason, 0) + 1
            if bool(metadata.get("main_brain_override_applied", False)):
                override_applied_count += 1
        pending_jobs = [
            row
            for row in self.store.list_jobs(limit=50)
            if str(row.get("task_type", "")).strip() == "initiative_ping"
            and str(row.get("status", "")).strip() in {"pending", "retry_wait", "running", "queued_transport", "sent"}
            and (not thread or int(row.get("thread_id", 0) or 0) == int(thread["id"]))
        ][:limit]
        queue_counts = {
            "pending": len(list(send_queue_dir.glob("*.json"))) if isinstance(send_queue_dir, Path) and send_queue_dir.exists() else 0,
            "sent": len(list(sent_dir.glob("*.json"))) if isinstance(sent_dir, Path) and sent_dir.exists() else 0,
            "failed": len(list(failed_dir.glob("*.json"))) if isinstance(failed_dir, Path) and failed_dir.exists() else 0,
        }
        return {
            "mode": mode,
            "thread_key": normalized_thread_key,
            "chat_name": normalized_chat_name,
            "channel": channel,
            "probe": probe,
            "gate_level_summary": gate_level_summary,
            "hard_block_reason_counts": hard_block_reason_counts,
            "soft_block_reason_counts": soft_block_reason_counts,
            "override_applied_count": override_applied_count,
            "thread": {
                "exists": bool(thread),
                "allow_proactive": bool(thread.get("allow_proactive", 1)) if thread else False,
                "last_message_at": str(thread.get("last_message_at", "") or "") if thread else "",
            },
            "contact": {
                "exists": bool(contact),
                "initiative_enabled": bool(contact.get("initiative_enabled", 1)) if contact else False,
                "last_initiative_at": str(contact.get("last_initiative_at", "") or "") if contact else "",
                "initiative_note": str(contact.get("initiative_note", "") or "") if contact else "",
            },
            "queue": {
                "send_queue_available": isinstance(send_queue_dir, Path),
                "send_queue_dir": str(send_queue_dir) if isinstance(send_queue_dir, Path) else "",
                "counts": queue_counts,
            },
            "transport_state": dict(helper.get("transport_state", {})),
            "whitelist": list(helper.get("whitelist", [])),
            "candidates": candidates,
            "pending_jobs": pending_jobs,
        }

    def run_self_revision(
        self,
        *,
        thread_key: str | None = None,
        chat_name: str | None = None,
        channel: str = "wechat",
        corrections: list[str] | None = None,
        apply_patch: bool = True,
    ) -> dict[str, Any]:
        return run_self_revision_cycle(
            config=self.config,
            runner=self.runner,
            memory=self.memory,
            store=self.store,
            thread_key=str(thread_key or chat_name or "").strip(),
            chat_name=str(chat_name or thread_key or "").strip(),
            channel=channel,
            extra_corrections=corrections,
            apply_patch=apply_patch,
        )

    def stream_tick(self, *, stream_name: str, dry_run: bool = False) -> dict[str, Any]:
        with self._memory_lock:
            stream_name = str(stream_name or "").strip()
            if stream_name == "maintenance_stream":
                result = self.memory.run_reflect_cycle(window_hours=self.config.memory.reflection_window_hours, dry_run=dry_run)
            elif stream_name == "association_stream":
                result = self.memory.run_think_cycle(sample_size=self.config.memory.thought_sample_size, dry_run=dry_run)
            elif stream_name == "social_stream":
                result = self.memory.run_initiative_cycle(dry_run=dry_run)
            elif stream_name == "deep_dream_cycle":
                result = self.memory.run_dream_cycle(sample_size=self.config.memory.dream_sample_size, dry_run=dry_run)
            else:
                raise ValueError(f"unsupported stream_name: {stream_name}")
            record = self.memory.record_stream_run(stream_name, status="ok", note="stream_tick", payload=result)
            return {"stream_name": stream_name, "dry_run": bool(dry_run), "result": result, "record": record}

    def backfill_vector_memory(
        self,
        *,
        thread_key: str | None = None,
        chat_name: str | None = None,
        channel: str | None = None,
    ) -> dict[str, Any]:
        with self._memory_lock:
            return self.memory.backfill_vector_memory(channel=channel, thread_key=thread_key, chat_name=chat_name)

    def sync_private_memory(self, *, label: str | None = None) -> dict[str, Any]:
        with self._memory_lock:
            return self.memory.sync_private_memory(label=label)

    def reply_probe(self, payload: dict[str, Any]) -> dict[str, Any]:
        turn = self._parse_turn(payload)
        requested_mode = str(payload.get("mode", "") or "").strip().lower()
        incoming = turn.to_incoming_message()
        thread = self.store.find_thread(channel=turn.channel, thread_key=incoming.thread_key)
        history = list(reversed(self.store.recent_thread_messages(int(thread["id"]), self.config.memory.history_messages))) if thread else []
        contact = self.store.find_contact(turn.synthetic_contact) or {
            "display_name": turn.chat_name,
            "email": turn.synthetic_contact,
        }
        mind_context = self._mind_context(
            turn=turn,
            incoming=incoming,
            thread=thread or {"thread_key": incoming.thread_key},
            contact=contact,
            history=history,
        )
        capability_context = self.capabilities.summarize_turn(turn.text, turn.metadata)
        attention_state = build_attention_state(turn.text, channel=turn.channel, metadata=turn.metadata)
        with self._memory_lock:
            hybrid_packet = self.memory.sidecar_packet(turn.text, context=mind_context)
            graph_packet = self.memory.graph_sidecar_packet(turn.text, context=mind_context)
            legacy_packet = self.memory.legacy_sidecar_packet(turn.text, context=mind_context)

        def _render_probe(packet: dict[str, Any]) -> dict[str, Any]:
            context = TurnContext(
                channel=turn.channel,
                thread_key=incoming.thread_key,
                chat_name=turn.chat_name,
                sender=turn.sender,
                user_text=turn.text,
                sidecar=packet,
                attention_state=attention_state,
                emotion_state=dict(packet.get("state", {}).get("emotion_state", {})),
                history=history,
                mind_packet=packet,
                utterance_plan=dict(packet.get("state", {}).get("rewrite_state", {}).get("utterance_plan", {})),
                metadata=dict(turn.metadata or {}),
                capability_context=capability_context,
            )
            reply_plan = self.processor.generate(context, session_id=str((thread or {}).get("codex_session_id", "")))
            return {
                "tier": str(packet.get("tier", "")),
                "query_focus": str(packet.get("query_focus", "recent") or "recent"),
                "retrieval_mode": str(packet.get("retrieval_mode", "legacy")),
                "graph_confidence": float(packet.get("graph_confidence", 0.0) or 0.0),
                "fallback_lanes": list(packet.get("fallback_lanes", [])),
                "activation_trace_ids": list(packet.get("activation_trace_ids", [])),
                "memory_route": str(packet.get("memory_route", "")),
                "recall_confidence": float(packet.get("recall_confidence", 0.0) or 0.0),
                "relationship_summary": str(packet.get("relationship_state", {}).get("summary", "")),
                "relationship_motifs": list(packet.get("relationship_state", {}).get("recurring_motifs", [])),
                "unfinished_threads": list(packet.get("relationship_state", {}).get("unfinished_threads", [])),
                "tone_tendency": str(packet.get("relationship_state", {}).get("tone_tendency", "")),
                "trust_score": float(packet.get("relationship_state", {}).get("trust_score", 0.0) or 0.0),
                "closeness_score": float(packet.get("relationship_state", {}).get("closeness_score", 0.0) or 0.0),
                "continuity_score": float(packet.get("relationship_state", {}).get("continuity_score", 0.0) or 0.0),
                "episodic_lines": list(packet.get("episodic_recall", {}).get("lines", [])),
                "consciousness_lines": list(packet.get("consciousness_stream", {}).get("lines", [])),
                "vector_hits": list(packet.get("vector_hits", [])),
                "activation_state": dict(packet.get("activation_state", {})),
                "persona_blend": dict(packet.get("persona_blend", {})),
                "brain_state": dict(packet.get("brain_state", {})),
                "game_state": dict(packet.get("game_state", {})),
                "stream_influence": dict(packet.get("stream_influence", {})),
                "self_revision_state": dict(packet.get("self_revision_state", {})),
                "retrieval_trace": dict(packet.get("retrieval_trace", {})),
                "recall_reconstruction": dict((context.mind_packet or {}).get("recall_reconstruction", {})),
                "reply_plan": reply_plan.to_dict(),
            }

        probes = {
            "chat_name": turn.chat_name,
            "thread_key": incoming.thread_key,
            "channel": turn.channel,
            "query": turn.text,
            "hybrid": _render_probe(hybrid_packet),
            "graph_led": _render_probe(graph_packet),
            "graph": _render_probe(graph_packet),
            "legacy": _render_probe(legacy_packet),
        }
        if requested_mode in {"hybrid", "graph", "graph_led", "legacy"}:
            probes["selected_mode"] = requested_mode
            probes["selected"] = dict(probes[requested_mode])
        return probes

    def _mind_context(
        self,
        *,
        turn: ChatTurn,
        incoming: IncomingMessage,
        thread: dict[str, Any],
        contact: dict[str, Any],
        history: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return {
            "channel": turn.channel,
            "thread_key": str(thread.get("thread_key") or incoming.thread_key),
            "incoming_thread_key": incoming.thread_key,
            "message_id": incoming.message_id,
            "chat_name": turn.chat_name,
            "sender": turn.sender,
            "contact_display_name": str(contact.get("display_name") or ""),
            "recent_history": history,
            "attachments": list((turn.metadata or {}).get("attachments", [])) if isinstance((turn.metadata or {}).get("attachments"), list) else [],
            "recall_trigger_mode": self.config.memory.recall_trigger_mode,
            "mind_budget": {
                "fast_history_messages": self.config.memory.fast_history_messages,
                "recall_history_messages": self.config.memory.recall_history_messages,
                "fast_episodic_k": self.config.memory.fast_episodic_k,
                "recall_episodic_k": self.config.memory.recall_episodic_k,
                "fast_consciousness_k": self.config.memory.fast_consciousness_k,
                "recall_consciousness_k": self.config.memory.recall_consciousness_k,
            },
        }

    def _load_wechat_history_state(self) -> dict[str, Any]:
        if not self._wechat_history_state_path.exists():
            return {}
        try:
            payload = json.loads(self._wechat_history_state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            return {}
        return payload if isinstance(payload, dict) else {}

    def _save_wechat_history_state(self, payload: dict[str, Any]) -> None:
        atomic_write_text(
            self._wechat_history_state_path,
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        )

    def _resolve_wechat_history_bridge(self) -> dict[str, Any]:
        with self._wechat_history_lock:
            if self._wechat_history_bridge is not None:
                return dict(self._wechat_history_bridge)

            repo_root = self.config.runtime.repo_root
            helper_config_raw = str(self.config.autonomy.wechat_helper_config_path or "").strip()
            helper_config_path = Path(helper_config_raw).expanduser() if helper_config_raw else repo_root / "windows_helper" / "wechat_helper.live.json"
            if not helper_config_path.is_absolute():
                helper_config_path = (repo_root / helper_config_path).resolve()

            helper_payload: dict[str, Any] = {}
            if helper_config_path.exists():
                try:
                    loaded = json.loads(helper_config_path.read_text(encoding="utf-8"))
                    if isinstance(loaded, dict):
                        helper_payload = loaded
                except (OSError, ValueError, json.JSONDecodeError):
                    helper_payload = {}

            windows_root = ""
            if _is_windows_abs_path(str(repo_root)):
                windows_root = str(repo_root).replace("\\", "/")
            if not windows_root and _is_windows_abs_path(self.config.autonomy.wechat_helper_windows_repo_root):
                windows_root = str(self.config.autonomy.wechat_helper_windows_repo_root).replace("\\", "/")
            if not windows_root and _is_windows_abs_path(str(Path.cwd())):
                windows_root = str(Path.cwd()).replace("\\", "/")
            if not windows_root:
                env_root = str(os.environ.get("HOLO_WINDOWS_REPO_ROOT", "")).strip()
                if _is_windows_abs_path(env_root):
                    windows_root = env_root.replace("\\", "/")
            if not windows_root:
                for key in (
                    "pause_file",
                    "state_file",
                    "transport_state_file",
                    "receipt_dir",
                    "send_queue_dir",
                    "inbox_dir",
                    "outbox_file",
                    "pyweixin_repo_path",
                    "pywinauto_process_path",
                ):
                    windows_root = _windows_repo_root_from_path(helper_payload.get(key))
                    if windows_root:
                        break

            windows_helper_config = ""
            if _is_windows_abs_path(helper_config_raw):
                windows_helper_config = helper_config_raw.replace("\\", "/")
            elif windows_root:
                windows_helper_config = f"{windows_root.rstrip('/')}/{helper_config_raw or 'windows_helper/wechat_helper.live.json'}"

            local_wrapper = repo_root / "windows_helper" / "invoke_wechat_history.ps1"
            windows_wrapper = f"{windows_root.rstrip('/')}/windows_helper/invoke_wechat_history.ps1" if windows_root else ""
            bridge = {
                "available": bool(windows_root and windows_helper_config and local_wrapper.exists()),
                "windows_repo_root": windows_root,
                "windows_helper_config_path": windows_helper_config,
                "windows_wrapper_path": windows_wrapper,
                "local_wrapper_path": str(local_wrapper),
                "local_helper_config_path": str(helper_config_path),
            }
            self._wechat_history_bridge = dict(bridge)
            return bridge

    def _should_refresh_wechat_history(self, turn: ChatTurn, sidecar: dict[str, Any]) -> bool:
        if turn.channel != "wechat":
            return False
        if not self.config.memory.active_wechat_history_enabled:
            return False
        query = turn.text.lower()
        if str(sidecar.get("tier", "")).strip().lower() in {"recall", "deep_recall"}:
            return True
        return any(marker in query for marker in WECHAT_HISTORY_EXPLICIT_HINTS)

    def refresh_wechat_history(self, payload: dict[str, Any]) -> dict[str, Any]:
        chat_name = str(payload.get("chat_name", "")).strip()
        if not chat_name:
            raise ValueError("`chat_name` is required")
        channel = str(payload.get("channel", "wechat")).strip() or "wechat"
        if channel != "wechat":
            return {"status": "skipped_non_wechat", "chat_name": chat_name, "channel": channel}

        thread_key = str(payload.get("thread_key", "")).strip()
        query = str(payload.get("query", "")).strip()
        force = bool(payload.get("force", False))
        limit = int(payload.get("limit", self.config.memory.active_wechat_history_limit) or self.config.memory.active_wechat_history_limit)
        page_turns = int(payload.get("page_turns", self.config.memory.active_wechat_history_page_turns) or self.config.memory.active_wechat_history_page_turns)
        include_visible = bool(payload.get("include_visible", self.config.memory.active_wechat_history_include_visible))
        include_captures = bool(payload.get("include_captures", self.config.memory.active_wechat_history_include_captures))
        timeout_seconds = int(payload.get("timeout_seconds", self.config.memory.active_wechat_history_timeout_seconds) or self.config.memory.active_wechat_history_timeout_seconds)
        cooldown_seconds = int(payload.get("cooldown_seconds", self.config.memory.active_wechat_history_cooldown_seconds) or self.config.memory.active_wechat_history_cooldown_seconds)
        origin_recall = _is_origin_recall_query(query)
        if origin_recall:
            limit = max(limit, int(self.config.memory.active_wechat_history_deep_limit))
            page_turns = max(page_turns, int(self.config.memory.active_wechat_history_deep_page_turns))
            timeout_seconds = max(timeout_seconds, int(self.config.memory.active_wechat_history_deep_timeout_seconds))
            cooldown_seconds = min(cooldown_seconds, int(self.config.memory.active_wechat_history_deep_cooldown_seconds))
        refresh_key = thread_key or chat_name

        bridge = self._resolve_wechat_history_bridge()
        if not bridge.get("available"):
            report = {
                "status": "unavailable",
                "chat_name": chat_name,
                "thread_key": thread_key,
                "query": query,
                "bridge": bridge,
            }
            self.logger.warning("active memory refresh unavailable for %s: %s", chat_name, bridge)
            return report

        with self._wechat_history_lock:
            state = self._load_wechat_history_state()
            history_state = state.get(refresh_key, {}) if isinstance(state.get(refresh_key), dict) else {}
            last_success_at = float(history_state.get("last_success_at", 0.0) or 0.0)
            remaining = max(0, cooldown_seconds - int(time.time() - last_success_at))
            if not force and cooldown_seconds > 0 and last_success_at and remaining > 0:
                report = {
                    "status": "skipped_cooldown",
                    "chat_name": chat_name,
                    "thread_key": thread_key,
                    "query": query,
                    "cooldown_seconds": cooldown_seconds,
                    "remaining_seconds": remaining,
                    "last_status": str(history_state.get("last_status", "")),
                }
                self.logger.info(
                    "active memory refresh skipped for %s because cooldown remains %ss",
                    chat_name,
                    remaining,
                )
                return report

        command = [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(bridge["windows_wrapper_path"]),
            "-ConfigPath",
            str(bridge["windows_helper_config_path"]),
            "-ChatName",
            chat_name,
            "-Limit",
            str(max(1, limit)),
            "-PageTurns",
            str(max(0, page_turns)),
        ]
        if not include_visible:
            command.append("-NoVisible")
        if not include_captures:
            command.append("-NoCaptures")
        if force:
            command.append("-Force")

        started_at = time.perf_counter()
        self.logger.info(
            "active memory refresh start chat=%s thread=%s limit=%s page_turns=%s origin=%s query=%s",
            chat_name,
            thread_key or chat_name,
            limit,
            page_turns,
            origin_recall,
            compact_text(query, 120),
        )
        completed = subprocess.run(
            command,
            capture_output=True,
            timeout=max(30, timeout_seconds),
        )
        elapsed_ms = int((time.perf_counter() - started_at) * 1000)
        stdout = _decode_windows_process_output(completed.stdout).strip()
        stderr = _decode_windows_process_output(completed.stderr).strip()
        if completed.returncode != 0:
            report = {
                "status": "error",
                "chat_name": chat_name,
                "thread_key": thread_key,
                "query": query,
                "returncode": completed.returncode,
                "stdout_excerpt": compact_text(stdout, 280),
                "stderr_excerpt": compact_text(stderr, 280),
                "elapsed_ms": elapsed_ms,
            }
            self.logger.warning(
                "active memory refresh failed for %s returncode=%s stderr=%s",
                chat_name,
                completed.returncode,
                compact_text(stderr or stdout, 240),
            )
            return report

        try:
            helper_report = json.loads(stdout) if stdout else {}
        except json.JSONDecodeError as exc:
            report = {
                "status": "error",
                "chat_name": chat_name,
                "thread_key": thread_key,
                "query": query,
                "detail": f"invalid_json:{exc}",
                "stdout_excerpt": compact_text(stdout, 280),
                "stderr_excerpt": compact_text(stderr, 280),
                "elapsed_ms": elapsed_ms,
            }
            self.logger.warning(
                "active memory refresh returned non-JSON for %s: %s",
                chat_name,
                compact_text(stdout or stderr, 240),
            )
            return report

        if not isinstance(helper_report, dict):
            helper_report = {"status": "error", "detail": "invalid_report"}
        report = dict(helper_report)
        report.setdefault("status", "ok")
        report["chat_name"] = chat_name
        report["thread_key"] = thread_key
        report["query"] = query
        report["elapsed_ms"] = elapsed_ms
        report["cooldown_seconds"] = cooldown_seconds
        report["command"] = {
            "limit": limit,
            "page_turns": page_turns,
            "include_visible": include_visible,
            "include_captures": include_captures,
            "origin_recall": origin_recall,
        }
        if str(report.get("status", "")).strip() == "ingested":
            with self._memory_lock:
                report["mind_graph_rebuild"] = self.memory.backfill_mind_graph(dry_run=False)
                report["game_state_sync"] = self.memory.mark_active_history_refresh(
                    channel=channel,
                    thread_key=thread_key or chat_name,
                    chat_name=chat_name,
                    query=query,
                )
        with self._wechat_history_lock:
            state = self._load_wechat_history_state()
            now_ts = time.time()
            saved = {
                "chat_name": chat_name,
                "thread_key": thread_key,
                "query": query,
                "last_attempt_at": now_ts,
                "last_status": str(report.get("status", "")),
                "elapsed_ms": elapsed_ms,
                "history_digest": str(report.get("history_digest", "")),
                "export_path": str(report.get("export_path", "")),
            }
            if str(report.get("status", "")).strip() in {"ingested", "skipped_duplicate_history"}:
                saved["last_success_at"] = now_ts
            elif isinstance(state.get(refresh_key), dict):
                saved["last_success_at"] = float(state[refresh_key].get("last_success_at", 0.0) or 0.0)
            state[refresh_key] = saved
            self._save_wechat_history_state(state)
        self.logger.info(
            "active memory refresh finished chat=%s status=%s messages=%s digest=%s elapsed_ms=%s",
            chat_name,
            report.get("status", ""),
            report.get("message_count", 0),
            report.get("history_digest", ""),
            elapsed_ms,
        )
        return report

    def _schedule_deferred_reply(
        self,
        *,
        thread: dict[str, Any],
        contact: dict[str, Any],
        stored_message: dict[str, Any],
        turn: ChatTurn,
        selected_action: dict[str, Any],
        defer_reason: str,
    ) -> int:
        available_at = (
            datetime.now(timezone.utc).replace(microsecond=0)
            + timedelta(seconds=max(90, int(self.config.memory.attention_tick_interval_seconds) * 20))
        ).isoformat().replace("+00:00", "Z")
        return self.store.enqueue_job(
            task_type="deferred_reply",
            priority=80,
            message_row_id=int(stored_message["id"]),
            thread_id=int(thread["id"]),
            contact_id=int(contact["id"]),
            available_at=available_at,
            payload={
                "source": "reply_api.defer_reply",
                "chat_name": turn.chat_name,
                "thread_key": thread.get("thread_key") or turn.thread_key,
                "channel": turn.channel,
                "sender": turn.sender,
                "defer_reason": defer_reason,
                "selected_action": dict(selected_action),
            },
        )

    def _record_subject_action(
        self,
        *,
        turn: ChatTurn,
        incoming: IncomingMessage,
        sidecar: dict[str, Any],
    ) -> dict[str, Any]:
        with self._memory_lock:
            return self.memory.record_action_selection(
                channel=turn.channel,
                thread_key=incoming.thread_key,
                chat_name=turn.chat_name,
                message_id=incoming.message_id,
                query=turn.text,
                intent_state=dict(sidecar.get("intent_state_v4", sidecar.get("intent_state_v3", sidecar.get("intent_state_v2", sidecar.get("intent_state", {}))))),
                action_market=list(sidecar.get("action_market_v4", sidecar.get("action_market_v3", sidecar.get("action_market_v2", sidecar.get("action_market", []))))),
                selected_action=dict(sidecar.get("selected_action", {})),
                expression_budget=int(sidecar.get("expression_budget_v4", sidecar.get("expression_budget_v3", sidecar.get("expression_budget_v2", sidecar.get("expression_budget", 0)))) or 0),
                silence_reason=str(sidecar.get("silence_reason", "") or ""),
                defer_reason=str(sidecar.get("defer_reason", "") or ""),
                action_rationale=str(sidecar.get("action_rationale", "") or ""),
                world_state=dict(sidecar.get("world_state", {})),
            )

    def _record_consciousness_entry(
        self,
        *,
        turn: ChatTurn,
        incoming: IncomingMessage,
        event_row_id: int | None,
        entry_type: str,
        selected_action: str = "",
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        with self._memory_lock:
            return self.memory.record_consciousness_entry(
                channel=turn.channel,
                thread_key=incoming.thread_key,
                chat_name=turn.chat_name,
                message_id=incoming.message_id,
                event_row_id=event_row_id,
                entry_type=entry_type,
                selected_action=selected_action,
                payload=payload or {},
            )

    def _ingest_event(
        self,
        *,
        payload: dict[str, Any],
        turn: ChatTurn,
        incoming: IncomingMessage,
        history: list[dict[str, Any]],
    ) -> dict[str, Any]:
        event_row = self.store.enqueue_event(
            event_type="incoming_message",
            channel=turn.channel,
            thread_key=incoming.thread_key,
            chat_name=turn.chat_name,
            message_id=incoming.message_id,
            status="received",
            payload={
                "chat_name": turn.chat_name,
                "sender": turn.sender,
                "channel": turn.channel,
                "thread_key": incoming.thread_key,
                "history_size": len(history),
                "text": turn.text,
                "metadata": dict(turn.metadata or {}),
                "raw_payload": dict(payload),
            },
        )
        event_row_id = int(event_row.get("id", 0) or 0)
        deliberation_trace_id = f"event-{event_row_id}-{stable_digest(incoming.message_id, incoming.thread_key, turn.text)[:12]}"
        self._record_consciousness_entry(
            turn=turn,
            incoming=incoming,
            event_row_id=event_row_id,
            entry_type="ingest_event",
            payload={
                "deliberation_trace_id": deliberation_trace_id,
                "history_size": len(history),
            },
        )
        return {
            "event_row_id": event_row_id,
            "deliberation_trace_id": deliberation_trace_id,
        }

    def _build_capability_context(self, turn: ChatTurn, *, eager_network: bool) -> dict[str, Any]:
        return self.capabilities.summarize_turn(turn.text, turn.metadata, eager_network=eager_network)

    @staticmethod
    def _normalize_selected_action(sidecar: dict[str, Any]) -> dict[str, Any]:
        allowed = {
            "silence",
            "defer_reply",
            "reply_once",
            "reply_multi",
            "external_lookup",
            "history_refresh",
            "visual_recall",
            "push_back",
            "counter_offer",
            "continuity_defense",
            "proactive_ping",
            "operator_self_fix",
        }
        selected = dict(sidecar.get("selected_action", {})) if isinstance(sidecar.get("selected_action", {}), dict) else {}
        selected_type = str(selected.get("action_type", "reply_once") or "reply_once")
        if selected_type in allowed:
            return selected
        for candidate in list(sidecar.get("action_market", [])):
            candidate_type = str(candidate.get("action_type", "")).strip()
            if candidate_type in allowed:
                return dict(candidate)
        return {"action_type": "reply_once"}

    @staticmethod
    def _speech_action(action_type: str) -> bool:
        return action_type in {"reply_once", "reply_multi", "push_back", "counter_offer", "continuity_defense"}

    def handle_reply(self, payload: dict[str, Any]) -> dict[str, Any]:
        turn = self._parse_turn(payload)
        if not turn.text.strip():
            return {"action": "ignore", "reason": "empty_text"}
        if any(hint in turn.text for hint in SYSTEM_EVENT_HINTS):
            return {"action": "ignore", "reason": "system_event"}

        incoming = turn.to_incoming_message()
        record = self.store.record_inbound(incoming)
        if record.get("duplicate") and not record.get("awaiting_reply"):
            return {
                "action": "ignore",
                "reason": "duplicate",
                "message_id": incoming.message_id,
                "thread_key": incoming.thread_key,
            }

        history = list(reversed(self.store.recent_thread_messages(int(record["thread"]["id"]), self.config.memory.history_messages)))
        if turn.channel == "wechat" and _looks_like_recent_outbound_echo(turn.text, history, turn.metadata):
            return {
                "action": "ignore",
                "reason": "outbound_echo",
                "thread_key": incoming.thread_key,
                "message_id": incoming.message_id,
            }

        event_info = self._ingest_event(payload=payload, turn=turn, incoming=incoming, history=history)
        event_row_id = int(event_info["event_row_id"])
        deliberation_trace_id = str(event_info["deliberation_trace_id"])
        mind_context = self._mind_context(
            turn=turn,
            incoming=incoming,
            thread=record["thread"],
            contact=record["contact"],
            history=history,
        )
        capability_context = self._build_capability_context(turn, eager_network=False)
        mind_context["capability_context"] = capability_context
        mind_context["deliberation_trace_id"] = deliberation_trace_id
        with self._memory_lock:
            sidecar = self.memory.sidecar_packet(turn.text, context=mind_context)
        selected_action = self._normalize_selected_action(sidecar)
        sidecar["selected_action"] = selected_action
        selected_action_type = str(selected_action.get("action_type", "reply_once") or "reply_once")
        self._record_subject_action(turn=turn, incoming=incoming, sidecar=sidecar)
        self.store.update_event_decision(
            event_row_id,
            status="decided",
            decision={
                "selected_action": dict(selected_action),
                "expression_budget": int(sidecar.get("expression_budget_v4", sidecar.get("expression_budget_v3", sidecar.get("expression_budget_v2", sidecar.get("expression_budget", 0)))) or 0),
                "action_rationale": str(sidecar.get("action_rationale", "") or ""),
                "deliberation_trace_id": deliberation_trace_id,
            },
        )
        self._record_consciousness_entry(
            turn=turn,
            incoming=incoming,
            event_row_id=event_row_id,
            entry_type="subject_decide",
            selected_action=selected_action_type,
            payload={
                "intent_state": dict(sidecar.get("intent_state_v4", sidecar.get("intent_state_v3", sidecar.get("intent_state_v2", sidecar.get("intent_state", {}))))),
                "action_market": list(sidecar.get("action_market_v4", sidecar.get("action_market_v3", sidecar.get("action_market_v2", sidecar.get("action_market", []))))),
                "expression_budget": int(sidecar.get("expression_budget_v4", sidecar.get("expression_budget_v3", sidecar.get("expression_budget_v2", sidecar.get("expression_budget", 0)))) or 0),
                "action_rationale": str(sidecar.get("action_rationale", "") or ""),
                "lookup_reason": str(sidecar.get("lookup_reason", "") or ""),
                "deliberation_trace_id": deliberation_trace_id,
                "world_snapshot": dict(sidecar.get("world_state", {})),
                "autobiographical_snapshot": dict(sidecar.get("autobiographical_state", {})),
                "goal_snapshot": dict(sidecar.get("goal_state", {})),
                "goal_alignment": dict(sidecar.get("goal_alignment", {})),
                "identity_consistency": dict(sidecar.get("identity_consistency", {})),
                "chapter_transition": str(sidecar.get("chapter_relevance", "") or ""),
                "self_update_reason": str(sidecar.get("self_narrative_hint", "") or ""),
                "counterfactual_set": [
                    dict(item.get("predicted_outcome", {})) | {"action_type": str(item.get("action_type", ""))}
                    for item in list(sidecar.get("action_market_v4", sidecar.get("action_market_v3", sidecar.get("action_market_v2", sidecar.get("action_market", [])))))[:3]
                ],
                "selected_prediction": dict(sidecar.get("selected_prediction", {})),
            },
        )

        if selected_action_type == "silence":
            result = {
                "action": "silence",
                "reason": str(sidecar.get("silence_reason", "") or "silence_selected"),
                "thread_key": incoming.thread_key,
                "message_id": incoming.message_id,
                "selected_action": selected_action,
                "expression_budget": int(sidecar.get("expression_budget_v4", sidecar.get("expression_budget_v3", sidecar.get("expression_budget_v2", sidecar.get("expression_budget", 0)))) or 0),
                "action_rationale": str(sidecar.get("action_rationale", "") or ""),
                "deliberation_trace_id": deliberation_trace_id,
            }
            self.store.update_event_result(event_row_id, status="completed", result=result)
            self._record_consciousness_entry(
                turn=turn,
                incoming=incoming,
                event_row_id=event_row_id,
                entry_type="selected_silence",
                selected_action="silence",
                payload=result,
            )
            return result

        if selected_action_type == "defer_reply":
            deferred_job_id = self._schedule_deferred_reply(
                thread=record["thread"],
                contact=record["contact"],
                stored_message=record["message"],
                turn=turn,
                selected_action=selected_action,
                defer_reason=str(sidecar.get("defer_reason", "") or "defer_reply_selected"),
            )
            result = {
                "action": "defer_reply",
                "reason": str(sidecar.get("defer_reason", "") or "defer_reply_selected"),
                "thread_key": incoming.thread_key,
                "message_id": incoming.message_id,
                "job_id": deferred_job_id,
                "selected_action": selected_action,
                "expression_budget": int(sidecar.get("expression_budget_v4", sidecar.get("expression_budget_v3", sidecar.get("expression_budget_v2", sidecar.get("expression_budget", 0)))) or 0),
                "action_rationale": str(sidecar.get("action_rationale", "") or ""),
                "deliberation_trace_id": deliberation_trace_id,
            }
            self.store.update_event_result(event_row_id, status="deferred", result=result)
            self._record_consciousness_entry(
                turn=turn,
                incoming=incoming,
                event_row_id=event_row_id,
                entry_type="selected_defer",
                selected_action="defer_reply",
                payload=result,
            )
            return result

        if selected_action_type == "history_refresh" and self._should_refresh_wechat_history(turn, sidecar):
            refresh_report = self.refresh_wechat_history(
                {
                    "chat_name": turn.chat_name,
                    "thread_key": incoming.thread_key,
                    "channel": turn.channel,
                    "query": turn.text,
                    "force": True,
                }
            )
            if str(refresh_report.get("status", "")).strip() == "ingested":
                with self._memory_lock:
                    self.memory.mark_active_history_refresh(
                        channel=turn.channel,
                        thread_key=incoming.thread_key,
                        chat_name=turn.chat_name,
                        query=turn.text,
                    )
                    sidecar = self.memory.sidecar_packet(turn.text, context=mind_context)
                selected_action = self._normalize_selected_action(sidecar)
                selected_action_type = str(selected_action.get("action_type", "reply_once") or "reply_once")
                self._record_consciousness_entry(
                    turn=turn,
                    incoming=incoming,
                    event_row_id=event_row_id,
                    entry_type="world_recalibration",
                    selected_action=selected_action_type,
                    payload={
                        "source": "history_refresh",
                        "world_snapshot": dict(sidecar.get("world_state", {})),
                        "autobiographical_snapshot": dict(sidecar.get("autobiographical_state", {})),
                        "goal_snapshot": dict(sidecar.get("goal_state", {})),
                        "counterfactual_set": [
                            dict(item.get("predicted_outcome", {})) | {"action_type": str(item.get("action_type", ""))}
                            for item in list(sidecar.get("action_market_v4", sidecar.get("action_market_v3", sidecar.get("action_market_v2", sidecar.get("action_market", [])))))[:3]
                        ],
                        "selected_prediction": dict(sidecar.get("selected_prediction", {})),
                    },
                )

        if selected_action_type == "external_lookup":
            executed_lookup = self.capabilities.execute_external_lookup(turn.text)
            capability_context = {
                **capability_context,
                "tool_requests": list(executed_lookup.get("tool_requests", capability_context.get("tool_requests", []))),
                "tool_context_lines": list(executed_lookup.get("tool_context_lines", [])),
                "evidence": dict(executed_lookup.get("evidence", {})),
                "lookup_completed": True,
            }
            payload["_stage6_lookup_report"] = executed_lookup
            mind_context["capability_context"] = capability_context
            with self._memory_lock:
                sidecar = self.memory.sidecar_packet(turn.text, context=mind_context)
            selected_action = self._normalize_selected_action(sidecar)
            selected_action_type = str(selected_action.get("action_type", "reply_once") or "reply_once")
            self._record_consciousness_entry(
                turn=turn,
                incoming=incoming,
                event_row_id=event_row_id,
                entry_type="world_recalibration",
                selected_action=selected_action_type,
                payload={
                    "source": "external_lookup",
                    "lookup_report": executed_lookup,
                    "world_snapshot": dict(sidecar.get("world_state", {})),
                    "autobiographical_snapshot": dict(sidecar.get("autobiographical_state", {})),
                    "goal_snapshot": dict(sidecar.get("goal_state", {})),
                    "counterfactual_set": [
                        dict(item.get("predicted_outcome", {})) | {"action_type": str(item.get("action_type", ""))}
                        for item in list(sidecar.get("action_market_v4", sidecar.get("action_market_v3", sidecar.get("action_market_v2", sidecar.get("action_market", [])))))[:3]
                    ],
                    "selected_prediction": dict(sidecar.get("selected_prediction", {})),
                },
            )
            if selected_action_type == "external_lookup":
                selected_action = next(
                    (
                        dict(item)
                        for item in list(sidecar.get("action_market", []))
                        if self._speech_action(str(item.get("action_type", "")).strip())
                    ),
                    {"action_type": "reply_once"},
                )
                sidecar["selected_action"] = selected_action

        payload = dict(payload)
        payload["_stage6_event_row_id"] = event_row_id
        payload["_stage6_deliberation_trace_id"] = deliberation_trace_id
        payload["_stage6_capability_context"] = capability_context
        payload["_stage6_prebuilt_sidecar"] = sidecar
        payload["_stage6_selected_action"] = selected_action
        result = self._handle_reply_stage5_legacy(payload)
        if self._speech_action(selected_action_type):
            result["selected_action"] = dict(selected_action)
            result["expression_budget"] = int(sidecar.get("expression_budget_v4", sidecar.get("expression_budget_v3", sidecar.get("expression_budget_v2", sidecar.get("expression_budget", 0)))) or 0)
            result["action_rationale"] = str(sidecar.get("action_rationale", "") or "")
            result["deliberation_trace_id"] = deliberation_trace_id
        self.store.update_event_result(event_row_id, status="completed", result=result)
        self._record_consciousness_entry(
            turn=turn,
            incoming=incoming,
            event_row_id=event_row_id,
            entry_type="execute_action",
            selected_action=selected_action_type,
            payload={
                "result": dict(result),
                "deliberation_trace_id": deliberation_trace_id,
                "autobiographical_snapshot": dict(sidecar.get("autobiographical_state", {})),
                "goal_snapshot": dict(sidecar.get("goal_state", {})),
                "goal_alignment": dict(sidecar.get("goal_alignment", {})),
                "identity_consistency": dict(sidecar.get("identity_consistency", {})),
            },
        )
        return result

    def _handle_reply_stage5_legacy(self, payload: dict[str, Any]) -> dict[str, Any]:
        started_at = time.perf_counter()
        turn = self._parse_turn(payload)
        if not turn.text.strip():
            return {"action": "ignore", "reason": "empty_text"}
        if any(hint in turn.text for hint in SYSTEM_EVENT_HINTS):
            return {"action": "ignore", "reason": "system_event"}

        incoming = turn.to_incoming_message()
        decision = self.policy.incoming_decision(incoming)
        record = self.store.record_inbound(incoming)
        if record.get("duplicate") and not record.get("awaiting_reply"):
            return {
                "action": "ignore",
                "reason": "duplicate",
                "message_id": incoming.message_id,
                "thread_key": incoming.thread_key,
            }

        thread = record["thread"]
        contact = record["contact"]
        stored_message = record["message"]
        history = list(reversed(self.store.recent_thread_messages(int(thread["id"]), self.config.memory.history_messages)))
        bundle = {
            "thread": thread,
            "contact": contact,
            "message": stored_message,
            "history": history,
        }

        if turn.channel == "wechat" and _looks_like_recent_outbound_echo(turn.text, history, turn.metadata):
            return {
                "action": "ignore",
                "reason": "outbound_echo",
                "thread_key": incoming.thread_key,
                "message_id": incoming.message_id,
            }

        mind_context = self._mind_context(
            turn=turn,
            incoming=incoming,
            thread=thread,
            contact=contact,
            history=history,
        )
        prebuilt_sidecar = dict(payload.get("_stage6_prebuilt_sidecar", {})) if isinstance(payload.get("_stage6_prebuilt_sidecar"), dict) else {}
        prebuilt_capability_context = dict(payload.get("_stage6_capability_context", {})) if isinstance(payload.get("_stage6_capability_context"), dict) else {}
        preselected_action = dict(payload.get("_stage6_selected_action", {})) if isinstance(payload.get("_stage6_selected_action"), dict) else {}
        if prebuilt_capability_context:
            mind_context["capability_context"] = prebuilt_capability_context
        if payload.get("_stage6_deliberation_trace_id"):
            mind_context["deliberation_trace_id"] = str(payload.get("_stage6_deliberation_trace_id"))
        visual_report: dict[str, Any] | None = None
        image_attachments = _image_attachments(turn.metadata)
        if image_attachments:
            sync_candidates = [
                item
                for item in image_attachments[: max(1, int(self.config.memory.visual_sync_max_count or 1))]
                if _attachment_size_mb(item) <= float(self.config.memory.visual_sync_max_size_mb or 8)
            ]
            queued_candidates = image_attachments[len(sync_candidates):]
            for attachment in queued_candidates:
                self.ingest_image(
                    {
                        "path": attachment.get("path", ""),
                        "note": f"queued visual ingest for {turn.chat_name}",
                        "source": "holo_host.reply_api.queued_visual",
                        "tags": [turn.channel, "visual_queue"],
                        "channel": turn.channel,
                        "thread_key": incoming.thread_key,
                        "chat_name": turn.chat_name,
                        "sync": False,
                    }
                )
            if sync_candidates:
                visual_report = self.ingest_image(
                    {
                        "path": sync_candidates[0].get("path", ""),
                        "note": f"sync visual ingest for {turn.chat_name}",
                        "source": "holo_host.reply_api.sync_visual",
                        "tags": [turn.channel, "visual_sync"],
                        "channel": turn.channel,
                        "thread_key": incoming.thread_key,
                        "chat_name": turn.chat_name,
                        "sync": True,
                    }
                )
        sidecar_started_at = time.perf_counter()
        if prebuilt_sidecar:
            sidecar = prebuilt_sidecar
        else:
            with self._memory_lock:
                sidecar = self.memory.sidecar_packet(turn.text, context=mind_context)
        active_history_report: dict[str, Any] | None = None
        active_history_ms = 0
        if not prebuilt_sidecar and self._should_refresh_wechat_history(turn, sidecar):
            refresh_started_at = time.perf_counter()
            active_history_report = self.refresh_wechat_history(
                {
                    "chat_name": turn.chat_name,
                    "thread_key": incoming.thread_key,
                    "channel": turn.channel,
                    "query": turn.text,
                }
            )
            active_history_ms = int((time.perf_counter() - refresh_started_at) * 1000)
            if str(active_history_report.get("status", "")).strip() == "ingested":
                self.logger.info(
                    "active memory refresh changed recall context for %s; rebuilding mind packet",
                    turn.chat_name,
                )
                with self._memory_lock:
                    sidecar = self.memory.sidecar_packet(turn.text, context=mind_context)
        sidecar_ms = int((time.perf_counter() - sidecar_started_at) * 1000)
        selected_action = dict(preselected_action or sidecar.get("selected_action", {}))
        selected_action_type = str(selected_action.get("action_type", "reply_once") or "reply_once")
        if selected_action_type not in {"silence", "defer_reply", "reply_once", "reply_multi", "external_lookup", "history_refresh", "visual_recall", "push_back", "counter_offer", "continuity_defense"}:
            for candidate in list(sidecar.get("action_market", [])):
                candidate_type = str(candidate.get("action_type", "")).strip()
                if candidate_type in {"silence", "defer_reply", "reply_once", "reply_multi", "external_lookup", "history_refresh", "visual_recall", "push_back", "counter_offer", "continuity_defense"}:
                    selected_action = dict(candidate)
                    selected_action_type = candidate_type
                    break
        last_action_selection = dict(sidecar.get("last_action_selection", {})) if isinstance(sidecar.get("last_action_selection", {}), dict) else {}
        if record.get("duplicate") and record.get("awaiting_reply"):
            if str(last_action_selection.get("message_id", "") or "") == incoming.message_id and selected_action_type in {"silence", "defer_reply"}:
                return {
                    "action": "ignore",
                    "reason": "already_decided",
                    "thread_key": incoming.thread_key,
                    "message_id": incoming.message_id,
                    "selected_action": selected_action_type,
                }
        if not prebuilt_sidecar and selected_action_type == "history_refresh" and active_history_report is None and self._should_refresh_wechat_history(turn, sidecar):
            refresh_started_at = time.perf_counter()
            active_history_report = self.refresh_wechat_history(
                {
                    "chat_name": turn.chat_name,
                    "thread_key": incoming.thread_key,
                    "channel": turn.channel,
                    "query": turn.text,
                    "force": True,
                }
            )
            active_history_ms += int((time.perf_counter() - refresh_started_at) * 1000)
            if str(active_history_report.get("status", "")).strip() == "ingested":
                with self._memory_lock:
                    sidecar = self.memory.sidecar_packet(turn.text, context=mind_context)
                selected_action = dict(sidecar.get("selected_action", {}))
                selected_action_type = str(selected_action.get("action_type", "reply_once") or "reply_once")

        self._record_subject_action(turn=turn, incoming=incoming, sidecar=sidecar)

        if selected_action_type == "silence":
            self.logger.info(
                "subject selected silence for %s message=%s reason=%s",
                turn.chat_name,
                incoming.message_id,
                sidecar.get("silence_reason", ""),
            )
            return {
                "action": "silence",
                "reason": str(sidecar.get("silence_reason", "") or "silence_selected"),
                "thread_key": incoming.thread_key,
                "message_id": incoming.message_id,
                "selected_action": selected_action,
                "expression_budget": int(sidecar.get("expression_budget", 0) or 0),
                "action_rationale": str(sidecar.get("action_rationale", "") or ""),
                "active_memory_refresh": active_history_report or {},
                "visual_ingest": visual_report or {},
            }

        if selected_action_type == "defer_reply":
            deferred_job_id = self._schedule_deferred_reply(
                thread=thread,
                contact=contact,
                stored_message=stored_message,
                turn=turn,
                selected_action=selected_action,
                defer_reason=str(sidecar.get("defer_reason", "") or "defer_reply_selected"),
            )
            self.logger.info(
                "subject deferred reply for %s message=%s job=%s reason=%s",
                turn.chat_name,
                incoming.message_id,
                deferred_job_id,
                sidecar.get("defer_reason", ""),
            )
            return {
                "action": "defer_reply",
                "reason": str(sidecar.get("defer_reason", "") or "defer_reply_selected"),
                "thread_key": incoming.thread_key,
                "message_id": incoming.message_id,
                "job_id": deferred_job_id,
                "selected_action": selected_action,
                "expression_budget": int(sidecar.get("expression_budget", 0) or 0),
                "action_rationale": str(sidecar.get("action_rationale", "") or ""),
                "active_memory_refresh": active_history_report or {},
                "visual_ingest": visual_report or {},
            }

        capability_started_at = time.perf_counter()
        capability_context = prebuilt_capability_context or self.capabilities.summarize_turn(turn.text, turn.metadata)
        capability_ms = int((time.perf_counter() - capability_started_at) * 1000)
        attention_state = build_attention_state(turn.text, channel=turn.channel, metadata=turn.metadata)
        turn_context = TurnContext(
            channel=turn.channel,
            thread_key=incoming.thread_key,
            chat_name=turn.chat_name,
            sender=turn.sender,
            user_text=turn.text,
            sidecar=sidecar,
            attention_state=attention_state,
            emotion_state=dict(sidecar.get("state", {}).get("emotion_state", {})),
            history=history,
            mind_packet=sidecar,
            utterance_plan=dict(sidecar.get("state", {}).get("rewrite_state", {}).get("utterance_plan", {})),
            metadata=dict(turn.metadata or {}),
            capability_context=capability_context,
        )
        try:
            reply_plan = self.processor.generate(turn_context, session_id=str(thread.get("codex_session_id", "")))
        except Exception as exc:  # noqa: BLE001
            self.logger.warning("processor failure for %s: %s", turn.chat_name, exc)
            return {
                "action": "ignore",
                "reason": "processor_failure",
                "thread_key": incoming.thread_key,
                "detail": str(exc),
            }
        sidecar = dict(turn_context.mind_packet or sidecar)
        processor_ms = int(reply_plan.timing_ms.get("processor_ms", 0))

        self.store.update_thread_session(int(thread["id"]), reply_plan.session_id)
        repair_started_at = time.perf_counter()
        with self._memory_lock:
            repaired = self.memory.repair_reply(turn.text, reply_plan.raw_text or reply_plan.text)
        repair_ms = int((time.perf_counter() - repair_started_at) * 1000)
        repaired_text = str(repaired.get("final_draft", reply_plan.text)).strip()
        bubbles = self._finalize_bubbles(
            repaired_text,
            channel=turn.channel,
            attention_state=reply_plan.attention_state or attention_state,
            emotion_state=reply_plan.emotion_state or turn_context.emotion_state,
            utterance_plan=reply_plan.utterance_plan or turn_context.utterance_plan,
            route=reply_plan.route,
            target_count=(reply_plan.turn_plan.bubble_target if reply_plan.turn_plan else 2),
            strict_target=bool(sidecar.get("selected_action", {})),
        )
        final_reply = " ".join(bubble.text for bubble in bubbles).strip()
        outbound = self.policy.outbound_decision(
            incoming_text=turn.text,
            reply_text=final_reply,
            recent_outbound_count=self.store.count_recent_outbound(int(contact["id"])),
            is_existing_thread=True,
            is_proactive=False,
            channel=turn.channel,
        )
        if not outbound.allowed:
            return {
                "action": "ignore",
                "reason": outbound.reason,
                "thread_key": incoming.thread_key,
                "risk_tags": outbound.risk_tags,
            }

        remote_message_id = f"{turn.channel}-out-{stable_digest(turn.chat_name, final_reply, incoming.message_id)}"
        outgoing = OutgoingMessage(
            recipient_email=str(contact["email"]),
            recipient_name=str(contact.get("display_name") or turn.chat_name),
            subject=turn.chat_name,
            body_text=final_reply,
            thread_key=incoming.thread_key,
            channel=turn.channel,
            metadata={
                "source": "reply_api",
                "codex_session_id": reply_plan.session_id,
                "reply_loop_outcome": repaired.get("outcome", ""),
                "priority": decision.priority,
                "bubbles": [bubble.to_dict() for bubble in bubbles],
                "turn_plan": reply_plan.turn_plan.to_dict() if reply_plan.turn_plan else {},
                "utterance_plan": dict(reply_plan.utterance_plan or turn_context.utterance_plan),
                "processor": reply_plan.processor,
                "route": reply_plan.route,
                "timing_ms": {
                    "sidecar_ms": sidecar_ms,
                    "active_history_ms": active_history_ms,
                    "capability_ms": capability_ms,
                    "processor_ms": processor_ms,
                    "repair_ms": repair_ms,
                },
                "active_memory_refresh": active_history_report or {},
                "visual_ingest": visual_report or {},
            },
        )
        self.store.record_outbound(
            thread_id=int(thread["id"]),
            contact_id=int(contact["id"]),
            remote_message_id=remote_message_id,
            outgoing=outgoing,
        )
        with self._memory_lock:
            self.memory.record_recall(list(sidecar.get("selected_memory_ids", [])), success=True)
        archive_metadata = {
            "chat_name": turn.chat_name,
            "sender": turn.sender,
            "channel": turn.channel,
            "thread_key": incoming.thread_key,
            "message_id": incoming.message_id,
            "outbound_message_id": remote_message_id,
            "source_ref": turn.source_ref,
            "is_group": turn.is_group,
            "mentioned": turn.mentioned,
            "codex_session_id": reply_plan.session_id,
            "reply_bubbles": [bubble.to_dict() for bubble in bubbles],
            "attention_state": (reply_plan.attention_state or attention_state).to_dict(),
            "turn_plan": reply_plan.turn_plan.to_dict() if reply_plan.turn_plan else {},
            "utterance_plan": dict(reply_plan.utterance_plan or turn_context.utterance_plan),
            "emotion_state": dict(reply_plan.emotion_state or turn_context.emotion_state),
            "random_state": dict(reply_plan.random_state),
            "processor": reply_plan.processor,
            "route": reply_plan.route,
            "mind_tier": str(sidecar.get("tier", "")),
            "recall_reason": str(sidecar.get("recall_reason", "")),
            "retrieval_mode": str(sidecar.get("retrieval_mode", "legacy")),
            "graph_confidence": float(sidecar.get("graph_confidence", 0.0) or 0.0),
            "fallback_lanes": list(sidecar.get("fallback_lanes", [])),
            "activation_trace_ids": list(sidecar.get("activation_trace_ids", [])),
            "graph_trace_summary": str(sidecar.get("graph_trace_summary", "") or ""),
            "recall_reconstruction": dict(sidecar.get("recall_reconstruction", {})),
            "selected_memory_ids": list(sidecar.get("selected_memory_ids", [])),
            "tool_requests": list(reply_plan.to_dict().get("tool_requests", [])),
            "capability_context": capability_context,
            "timing_ms": {
                "sidecar_ms": sidecar_ms,
                "active_history_ms": active_history_ms,
                "capability_ms": capability_ms,
                "processor_ms": processor_ms,
                "recall_reconstruct_ms": int(reply_plan.timing_ms.get("recall_reconstruct_ms", 0)),
                "repair_ms": repair_ms,
                "total_ms": int((time.perf_counter() - started_at) * 1000),
            },
            "active_memory_refresh": active_history_report or {},
            "visual_ingest": visual_report or {},
            **(turn.metadata or {}),
        }
        memory_write_report: dict[str, Any] = {}
        if self.config.memory.auto_observe:
            with self._memory_lock:
                observed = self.memory.observe_turn(
                    turn.text,
                    final_reply,
                    source="holo_host.reply_api",
                    tags=[turn.channel, "chat_reply"],
                    turn_id=incoming.message_id,
                    metadata=archive_metadata,
                )
            if isinstance(observed, dict):
                memory_write_report = observed
        else:
            with self._memory_lock:
                archived = self.memory.archive_turn(
                    turn.text,
                    final_reply,
                    source="holo_host.reply_api",
                    tags=[turn.channel, "chat_reply"],
                    turn_id=incoming.message_id,
                    metadata=archive_metadata,
                )
            if isinstance(archived, dict):
                memory_write_report = archived

        mind_graph_sync = dict(memory_write_report.get("mind_graph_sync", {})) if memory_write_report else {}
        if mind_graph_sync:
            self.logger.info(
                "mind graph sync status=%s thread=%s nodes=%s",
                mind_graph_sync.get("status", ""),
                incoming.thread_key,
                mind_graph_sync.get("node_count", 0),
            )

        total_ms = int((time.perf_counter() - started_at) * 1000)
        timing_ms = {
            "sidecar_ms": sidecar_ms,
            "active_history_ms": active_history_ms,
            "capability_ms": capability_ms,
            "processor_ms": processor_ms,
            "recall_reconstruct_ms": int(reply_plan.timing_ms.get("recall_reconstruct_ms", 0)),
            "repair_ms": repair_ms,
            "total_ms": total_ms,
        }
        self.logger.info(
            "reply route=%s processor=%s total_ms=%s chat=%s",
            reply_plan.route,
            reply_plan.processor,
            total_ms,
            turn.chat_name,
        )
        return {
            "action": "reply",
            "text": final_reply,
            "bubbles": [bubble.text for bubble in bubbles],
            "cadence_ms": [bubble.delay_ms for bubble in bubbles],
            "thread_key": incoming.thread_key,
            "message_id": incoming.message_id,
            "session_id": reply_plan.session_id,
            "reply_loop_outcome": repaired.get("outcome", ""),
            "priority": decision.priority,
            "chat_name": turn.chat_name,
            "attention_state": (reply_plan.attention_state or attention_state).to_dict(),
            "turn_plan": reply_plan.turn_plan.to_dict() if reply_plan.turn_plan else {},
            "utterance_plan": dict(reply_plan.utterance_plan or turn_context.utterance_plan),
            "emotion_state": dict(reply_plan.emotion_state or turn_context.emotion_state),
            "processor": reply_plan.processor,
            "route": reply_plan.route,
            "retrieval_mode": str(sidecar.get("retrieval_mode", "legacy")),
            "graph_confidence": float(sidecar.get("graph_confidence", 0.0) or 0.0),
            "fallback_lanes": list(sidecar.get("fallback_lanes", [])),
            "activation_trace_ids": list(sidecar.get("activation_trace_ids", [])),
            "recall_reconstruction": dict(sidecar.get("recall_reconstruction", {})),
            "mind_graph_sync": mind_graph_sync,
            "timing_ms": timing_ms,
            "active_memory_refresh": active_history_report or {},
            "visual_ingest": visual_report or {},
            "selected_action": dict(sidecar.get("selected_action", {})),
            "expression_budget": int(sidecar.get("expression_budget", 0) or 0),
            "action_rationale": str(sidecar.get("action_rationale", "") or ""),
        }

    def _parse_turn(self, payload: dict[str, Any]) -> ChatTurn:
        chat_name = str(payload.get("chat_name", "")).strip()
        text = str(payload.get("text", "")).strip()
        if not chat_name:
            raise ValueError("`chat_name` is required")
        return ChatTurn(
            chat_name=chat_name,
            text=_normalize_turn_text(text),
            sender=str(payload.get("sender", "")).strip(),
            channel=str(payload.get("channel", "wechat")).strip() or "wechat",
            thread_key=str(payload.get("thread_key", "")).strip(),
            message_id=str(payload.get("message_id", "")).strip(),
            ts=int(payload["ts"]) if payload.get("ts") not in (None, "") else None,
            is_group=bool(payload.get("is_group", False)),
            mentioned=bool(payload.get("mentioned", False)),
            source_ref=str(payload.get("source_ref", "")).strip(),
            metadata=self._normalize_metadata(payload),
        )

    def _normalize_metadata(self, payload: dict[str, Any]) -> dict[str, Any]:
        metadata = dict(payload.get("metadata") or {}) if isinstance(payload.get("metadata"), dict) else {}
        attachments = payload.get("attachments")
        if isinstance(attachments, list):
            metadata["attachments"] = [item for item in attachments if isinstance(item, dict)]
        return metadata

    def _finalize_bubbles(
        self,
        text: str,
        *,
        channel: str,
        attention_state: AttentionState,
        emotion_state: dict[str, Any],
        utterance_plan: dict[str, Any] | None,
        route: str,
        target_count: int = 2,
        strict_target: bool = False,
    ) -> list[ReplyBubble]:
        raw_bubbles = build_reply_bubbles(
            text,
            channel=channel,
            attention_state=attention_state,
            emotion_state=emotion_state,
            utterance_plan=utterance_plan,
            route=route,
            target_count=target_count,
            strict_target=strict_target,
        )
        finalized: list[ReplyBubble] = []
        for bubble in raw_bubbles:
            bubble_text = bubble.text.strip()
            if channel == "wechat":
                bubble_text = shape_wechat_reply(bubble_text)
            bubble_text = bubble_text.strip()
            if not bubble_text:
                continue
            if finalized and finalized[-1].text == bubble_text:
                continue
            finalized.append(ReplyBubble(text=bubble_text, delay_ms=max(0, bubble.delay_ms), purpose=bubble.purpose))
        if not finalized:
            fallback = shape_wechat_reply(text) if channel == "wechat" else text.strip()
            finalized.append(ReplyBubble(text=fallback or "咱在。", delay_ms=0, purpose="fallback"))
        return finalized


    def _benchmark_packet_build(
        self,
        *,
        query: str,
        thread_key: str,
        chat_name: str,
        channel: str,
        sender: str,
        iterations: int,
        warmup: int,
        target_tier: str,
    ) -> dict[str, Any]:
        timings: list[float] = []
        last_payload: dict[str, Any] = {}
        total_runs = max(1, int(warmup)) + max(1, int(iterations))
        for index in range(total_runs):
            started_at = time.perf_counter()
            payload = self.inspect_mind(
                query=query,
                thread_key=thread_key,
                chat_name=chat_name,
                channel=channel,
                sender=sender,
                include_graph_trace=True,
            )
            elapsed_ms = (time.perf_counter() - started_at) * 1000.0
            if index >= max(1, int(warmup)):
                timings.append(round(elapsed_ms, 2))
            last_payload = payload
        if not timings:
            timings = [0.0]
        return {
            "query": query,
            "target_tier": target_tier,
            "last_tier": str(last_payload.get("tier", "") or ""),
            "timings_ms": {
                "min": round(min(timings), 2),
                "max": round(max(timings), 2),
                "avg": round(sum(timings) / len(timings), 2),
            },
            "packet_cache": dict(self.memory.packet_cache_stats()),
        }


class _ReplyHTTPServer(ThreadingHTTPServer):
    def __init__(self, server_address: tuple[str, int], handler_cls: type[BaseHTTPRequestHandler], *, service: HoloReplyService):
        self.reply_service = service
        super().__init__(server_address, handler_cls)


def _handler_factory() -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server: _ReplyHTTPServer

        def log_message(self, fmt: str, *args: Any) -> None:
            self.server.reply_service.logger.info("http %s", fmt % args)

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            try:
                if parsed.path == "/health":
                    self._write_json(HTTPStatus.OK, self.server.reply_service.health())
                    return
                if parsed.path == "/revive-packet":
                    params = parse_qs(parsed.query)
                    packet = self.server.reply_service.revive_packet(
                        query=params.get("query", [None])[0],
                        path=params.get("path", [None])[0],
                    )
                    self._write_json(HTTPStatus.OK, packet)
                    return
                if parsed.path == "/mind-graph":
                    params = parse_qs(parsed.query)
                    payload = self.server.reply_service.inspect_graph(
                        thread_key=params.get("thread_key", [None])[0],
                        chat_name=params.get("chat_name", [None])[0],
                        channel=params.get("channel", ["wechat"])[0],
                        limit=int(params.get("limit", ["12"])[0]),
                    )
                    self._write_json(HTTPStatus.OK, payload)
                    return
                if parsed.path == "/inspect-mind":
                    params = parse_qs(parsed.query)
                    query = params.get("query", [""])[0]
                    if not str(query).strip():
                        self._write_json(HTTPStatus.BAD_REQUEST, {"error": "bad_request", "detail": "`query` is required"})
                        return
                    payload = self.server.reply_service.inspect_mind(
                        query=query,
                        thread_key=params.get("thread_key", [None])[0],
                        chat_name=params.get("chat_name", [None])[0],
                        channel=params.get("channel", ["wechat"])[0],
                        sender=params.get("sender", [None])[0],
                        include_graph_trace=params.get("include_graph_trace", ["1"])[0] not in {"0", "false", "False"},
                    )
                    self._write_json(HTTPStatus.OK, payload)
                    return
                if parsed.path == "/trace-recall":
                    params = parse_qs(parsed.query)
                    query = params.get("query", [""])[0]
                    if not str(query).strip():
                        self._write_json(HTTPStatus.BAD_REQUEST, {"error": "bad_request", "detail": "`query` is required"})
                        return
                    payload = self.server.reply_service.trace_recall(
                        query=query,
                        thread_key=params.get("thread_key", [None])[0],
                        chat_name=params.get("chat_name", [None])[0],
                        channel=params.get("channel", ["wechat"])[0],
                        limit=int(params.get("limit", ["8"])[0]),
                    )
                    self._write_json(HTTPStatus.OK, payload)
                    return
                if parsed.path == "/trace-hybrid-recall":
                    params = parse_qs(parsed.query)
                    query = params.get("query", [""])[0]
                    if not str(query).strip():
                        self._write_json(HTTPStatus.BAD_REQUEST, {"error": "bad_request", "detail": "`query` is required"})
                        return
                    payload = self.server.reply_service.trace_hybrid_recall(
                        query=query,
                        thread_key=params.get("thread_key", [None])[0],
                        chat_name=params.get("chat_name", [None])[0],
                        channel=params.get("channel", ["wechat"])[0],
                        limit=int(params.get("limit", ["8"])[0]),
                    )
                    self._write_json(HTTPStatus.OK, payload)
                    return
                if parsed.path == "/activation-state":
                    params = parse_qs(parsed.query)
                    payload = self.server.reply_service.activation_state(
                        thread_key=params.get("thread_key", [None])[0],
                        chat_name=params.get("chat_name", [None])[0],
                        channel=params.get("channel", ["wechat"])[0],
                    )
                    self._write_json(HTTPStatus.OK, payload)
                    return
                if parsed.path == "/vector-health":
                    self._write_json(HTTPStatus.OK, self.server.reply_service.vector_health())
                    return
                if parsed.path == "/brain-status":
                    self._write_json(HTTPStatus.OK, self.server.reply_service.brain_status())
                    return
                if parsed.path == "/self-model":
                    self._write_json(HTTPStatus.OK, self.server.reply_service.self_model())
                    return
                if parsed.path == "/autobiographical-state":
                    self._write_json(HTTPStatus.OK, self.server.reply_service.autobiographical_state())
                    return
                if parsed.path == "/goal-state":
                    self._write_json(HTTPStatus.OK, self.server.reply_service.goal_state())
                    return
                if parsed.path == "/self-continuity":
                    self._write_json(HTTPStatus.OK, self.server.reply_service.trace_self_continuity())
                    return
                if parsed.path == "/goal-arbitration":
                    self._write_json(HTTPStatus.OK, self.server.reply_service.trace_goal_arbitration())
                    return
                if parsed.path == "/world-state":
                    params = parse_qs(parsed.query)
                    payload = self.server.reply_service.world_state(
                        thread_key=params.get("thread_key", [None])[0],
                        chat_name=params.get("chat_name", [None])[0],
                        channel=params.get("channel", ["wechat"])[0],
                    )
                    self._write_json(HTTPStatus.OK, payload)
                    return
                if parsed.path == "/affect-state":
                    params = parse_qs(parsed.query)
                    payload = self.server.reply_service.affect_state(
                        thread_key=params.get("thread_key", [None])[0],
                        chat_name=params.get("chat_name", [None])[0],
                        channel=params.get("channel", ["wechat"])[0],
                    )
                    self._write_json(HTTPStatus.OK, payload)
                    return
                if parsed.path == "/intent-state":
                    params = parse_qs(parsed.query)
                    payload = self.server.reply_service.intent_state(
                        thread_key=params.get("thread_key", [None])[0],
                        chat_name=params.get("chat_name", [None])[0],
                        channel=params.get("channel", ["wechat"])[0],
                        query=params.get("query", [""])[0],
                    )
                    self._write_json(HTTPStatus.OK, payload)
                    return
                if parsed.path == "/action-market":
                    params = parse_qs(parsed.query)
                    payload = self.server.reply_service.action_market(
                        thread_key=params.get("thread_key", [None])[0],
                        chat_name=params.get("chat_name", [None])[0],
                        channel=params.get("channel", ["wechat"])[0],
                        query=params.get("query", [""])[0],
                        limit=int(params.get("limit", ["8"])[0]),
                    )
                    self._write_json(HTTPStatus.OK, payload)
                    return
                if parsed.path == "/deliberation-ledger":
                    params = parse_qs(parsed.query)
                    payload = self.server.reply_service.deliberation_ledger(
                        thread_key=params.get("thread_key", [None])[0],
                        chat_name=params.get("chat_name", [None])[0],
                        channel=params.get("channel", ["wechat"])[0],
                        limit=int(params.get("limit", ["24"])[0]),
                    )
                    self._write_json(HTTPStatus.OK, payload)
                    return
                if parsed.path == "/counterfactual":
                    params = parse_qs(parsed.query)
                    query = params.get("query", [""])[0]
                    if not str(query).strip():
                        self._write_json(HTTPStatus.BAD_REQUEST, {"error": "bad_request", "detail": "`query` is required"})
                        return
                    payload = self.server.reply_service.trace_counterfactual(
                        query=query,
                        thread_key=params.get("thread_key", [None])[0],
                        chat_name=params.get("chat_name", [None])[0],
                        channel=params.get("channel", ["wechat"])[0],
                        limit=int(params.get("limit", ["3"])[0]),
                    )
                    self._write_json(HTTPStatus.OK, payload)
                    return
                if parsed.path == "/world-calibration":
                    params = parse_qs(parsed.query)
                    payload = self.server.reply_service.trace_world_calibration(
                        thread_key=params.get("thread_key", [None])[0],
                        chat_name=params.get("chat_name", [None])[0],
                        channel=params.get("channel", ["wechat"])[0],
                    )
                    self._write_json(HTTPStatus.OK, payload)
                    return
                if parsed.path == "/drive-state":
                    params = parse_qs(parsed.query)
                    payload = self.server.reply_service.drive_state(
                        thread_key=params.get("thread_key", [None])[0],
                        chat_name=params.get("chat_name", [None])[0],
                        channel=params.get("channel", ["wechat"])[0],
                    )
                    self._write_json(HTTPStatus.OK, payload)
                    return
                if parsed.path == "/operator-status":
                    self._write_json(HTTPStatus.OK, self.server.reply_service.operator_status())
                    return
                if parsed.path == "/visual-memory":
                    params = parse_qs(parsed.query)
                    payload = self.server.reply_service.visual_memory(
                        thread_key=params.get("thread_key", [None])[0],
                        chat_name=params.get("chat_name", [None])[0],
                        channel=params.get("channel", ["wechat"])[0],
                    )
                    self._write_json(HTTPStatus.OK, payload)
                    return
                if parsed.path == "/trace-visual-recall":
                    params = parse_qs(parsed.query)
                    query = params.get("query", [""])[0]
                    if not str(query).strip():
                        self._write_json(HTTPStatus.BAD_REQUEST, {"error": "bad_request", "detail": "`query` is required"})
                        return
                    payload = self.server.reply_service.trace_visual_recall(
                        query=query,
                        thread_key=params.get("thread_key", [None])[0],
                        chat_name=params.get("chat_name", [None])[0],
                        channel=params.get("channel", ["wechat"])[0],
                        limit=int(params.get("limit", ["4"])[0]),
                    )
                    self._write_json(HTTPStatus.OK, payload)
                    return
                if parsed.path == "/initiative-market":
                    params = parse_qs(parsed.query)
                    payload = self.server.reply_service.initiative_market(
                        thread_key=params.get("thread_key", [None])[0],
                        chat_name=params.get("chat_name", [None])[0],
                        channel=params.get("channel", ["wechat"])[0],
                        limit=int(params.get("limit", ["8"])[0]),
                    )
                    self._write_json(HTTPStatus.OK, payload)
                    return
                if parsed.path == "/initiative-status":
                    params = parse_qs(parsed.query)
                    payload = self.server.reply_service.initiative_status(
                        thread_key=params.get("thread_key", [None])[0],
                        chat_name=params.get("chat_name", [None])[0],
                        channel=params.get("channel", ["wechat"])[0],
                        limit=int(params.get("limit", ["5"])[0]),
                    )
                    self._write_json(HTTPStatus.OK, payload)
                    return
                if parsed.path == "/stream-status":
                    self._write_json(HTTPStatus.OK, self.server.reply_service.stream_status())
                    return
                if parsed.path == "/reply-probe":
                    params = parse_qs(parsed.query)
                    query = params.get("query", [""])[0]
                    chat_name = params.get("chat_name", [None])[0] or params.get("thread_key", [""])[0]
                    if not str(query).strip() or not str(chat_name).strip():
                        self._write_json(
                            HTTPStatus.BAD_REQUEST,
                            {"error": "bad_request", "detail": "`query` and `chat_name` or `thread_key` are required"},
                        )
                        return
                    payload = self.server.reply_service.reply_probe(
                        {
                            "chat_name": chat_name,
                            "thread_key": params.get("thread_key", [None])[0] or "",
                            "channel": params.get("channel", ["wechat"])[0],
                            "sender": params.get("sender", [None])[0] or chat_name,
                            "text": query,
                        }
                    )
                    mode = str(params.get("mode", ["all"])[0] or "all")
                    if mode != "all":
                        payload = {
                            "chat_name": payload.get("chat_name", ""),
                            "thread_key": payload.get("thread_key", ""),
                            "channel": payload.get("channel", ""),
                            "query": payload.get("query", ""),
                            mode: payload.get(mode, {}),
                        }
                    self._write_json(HTTPStatus.OK, payload)
                    return
            except ValueError as exc:
                self._write_json(HTTPStatus.BAD_REQUEST, {"error": "bad_request", "detail": str(exc)})
                return
            except Exception as exc:  # noqa: BLE001
                self.server.reply_service.logger.exception("reply api get request failed")
                self._write_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "server_error", "detail": str(exc)})
                return
            self._write_json(HTTPStatus.NOT_FOUND, {"error": "not_found"})

        def do_POST(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            try:
                payload = self._read_json()
                if parsed.path == "/reply":
                    self._write_json(HTTPStatus.OK, self.server.reply_service.handle_reply(payload))
                    return
                if parsed.path == "/snapshot":
                    self._write_json(HTTPStatus.OK, self.server.reply_service.snapshot(payload))
                    return
                if parsed.path == "/restore-snapshot":
                    self._write_json(HTTPStatus.OK, self.server.reply_service.restore_snapshot(payload))
                    return
                if parsed.path == "/ingest-artifact":
                    self._write_json(HTTPStatus.OK, self.server.reply_service.ingest_artifact(payload))
                    return
                if parsed.path == "/ingest-image":
                    self._write_json(HTTPStatus.OK, self.server.reply_service.ingest_image(payload))
                    return
                if parsed.path == "/refresh-wechat-history":
                    self._write_json(HTTPStatus.OK, self.server.reply_service.refresh_wechat_history(payload))
                    return
                if parsed.path == "/backfill-vector-memory":
                    self._write_json(
                        HTTPStatus.OK,
                        self.server.reply_service.backfill_vector_memory(
                            thread_key=str(payload.get("thread_key", "")).strip() or None,
                            chat_name=str(payload.get("chat_name", "")).strip() or None,
                            channel=str(payload.get("channel", "")).strip() or None,
                        ),
                    )
                    return
                if parsed.path == "/sync-private-memory":
                    self._write_json(
                        HTTPStatus.OK,
                        self.server.reply_service.sync_private_memory(label=str(payload.get("label", "")).strip() or None),
                    )
                    return
                if parsed.path == "/reply-probe":
                    self._write_json(HTTPStatus.OK, self.server.reply_service.reply_probe(payload))
                    return
                if parsed.path == "/stream-tick":
                    self._write_json(
                        HTTPStatus.OK,
                        self.server.reply_service.stream_tick(
                            stream_name=str(payload.get("stream_name", "")).strip(),
                            dry_run=bool(payload.get("dry_run", False)),
                        ),
                    )
                    return
                if parsed.path == "/brain-mode":
                    self._write_json(
                        HTTPStatus.OK,
                        self.server.reply_service.set_brain_mode(
                            mode=str(payload.get("mode", "")).strip() or self.server.reply_service.config.memory.brain_mode_default,
                            note=str(payload.get("note", "")).strip(),
                        ),
                    )
                    return
                if parsed.path == "/self-revision":
                    self._write_json(
                        HTTPStatus.OK,
                        self.server.reply_service.run_self_revision(
                            thread_key=str(payload.get("thread_key", "")).strip() or None,
                            chat_name=str(payload.get("chat_name", "")).strip() or None,
                            channel=str(payload.get("channel", "wechat")).strip() or "wechat",
                            corrections=[str(item).strip() for item in payload.get("corrections", []) if str(item).strip()],
                            apply_patch=bool(payload.get("apply_patch", True)),
                        ),
                    )
                    return
                if parsed.path == "/initiative-probe":
                    self._write_json(
                        HTTPStatus.OK,
                        self.server.reply_service.initiative_probe(
                            thread_key=str(payload.get("thread_key", "")).strip() or None,
                            chat_name=str(payload.get("chat_name", "")).strip() or None,
                            channel=str(payload.get("channel", "wechat")).strip() or "wechat",
                            query=str(payload.get("query", "")).strip(),
                        ),
                    )
                    return
                if parsed.path == "/operator-probe":
                    self._write_json(
                        HTTPStatus.OK,
                        self.server.reply_service.operator_probe(
                            thread_key=str(payload.get("thread_key", "")).strip() or None,
                            chat_name=str(payload.get("chat_name", "")).strip() or None,
                            channel=str(payload.get("channel", "wechat")).strip() or "wechat",
                        ),
                    )
                    return
                if parsed.path == "/operator-cycle":
                    self._write_json(
                        HTTPStatus.OK,
                        self.server.reply_service.run_operator_cycle(
                            thread_key=str(payload.get("thread_key", "")).strip() or None,
                            chat_name=str(payload.get("chat_name", "")).strip() or None,
                            channel=str(payload.get("channel", "wechat")).strip() or "wechat",
                            reason=str(payload.get("reason", "reply_api")).strip() or "reply_api",
                        ),
                    )
                    return
                if parsed.path == "/initiative-run":
                    self._write_json(
                        HTTPStatus.OK,
                        self.server.reply_service.initiative_run(
                            thread_key=str(payload.get("thread_key", "")).strip() or None,
                            chat_name=str(payload.get("chat_name", "")).strip() or None,
                            channel=str(payload.get("channel", "wechat")).strip() or "wechat",
                            dry_run=bool(payload.get("dry_run", False)),
                        ),
                    )
                    return
                if parsed.path == "/trace-resistance":
                    self._write_json(
                        HTTPStatus.OK,
                        self.server.reply_service.trace_resistance(
                            thread_key=str(payload.get("thread_key", "")).strip() or None,
                            chat_name=str(payload.get("chat_name", "")).strip() or None,
                            channel=str(payload.get("channel", "wechat")).strip() or "wechat",
                            query=str(payload.get("query", "")).strip(),
                        ),
                    )
                    return
                if parsed.path == "/trace-action-selection":
                    self._write_json(
                        HTTPStatus.OK,
                        self.server.reply_service.trace_action_selection(
                            query=str(payload.get("query", "")).strip(),
                            thread_key=str(payload.get("thread_key", "")).strip() or None,
                            chat_name=str(payload.get("chat_name", "")).strip() or None,
                            channel=str(payload.get("channel", "wechat")).strip() or "wechat",
                            limit=int(payload.get("limit", 8) or 8),
                        ),
                    )
                    return
                if parsed.path == "/accept-stage3":
                    self._write_json(
                        HTTPStatus.OK,
                        self.server.reply_service.accept_stage3(
                            thread_key=str(payload.get("thread_key", "")).strip() or None,
                            chat_name=str(payload.get("chat_name", "")).strip() or None,
                            channel=str(payload.get("channel", "wechat")).strip() or "wechat",
                            sender=str(payload.get("sender", "")).strip() or None,
                            iterations=int(payload.get("iterations", 3) or 3),
                            warmup=int(payload.get("warmup", 1) or 1),
                        ),
                    )
                    return
                if parsed.path == "/accept-stage4":
                    self._write_json(
                        HTTPStatus.OK,
                        self.server.reply_service.accept_stage4(
                            thread_key=str(payload.get("thread_key", "")).strip() or None,
                            chat_name=str(payload.get("chat_name", "")).strip() or None,
                            channel=str(payload.get("channel", "wechat")).strip() or "wechat",
                            sender=str(payload.get("sender", "")).strip() or None,
                            iterations=int(payload.get("iterations", 3) or 3),
                            warmup=int(payload.get("warmup", 1) or 1),
                        ),
                    )
                    return
                if parsed.path == "/accept-stage5":
                    self._write_json(
                        HTTPStatus.OK,
                        self.server.reply_service.accept_stage5(
                            thread_key=str(payload.get("thread_key", "")).strip() or None,
                            chat_name=str(payload.get("chat_name", "")).strip() or None,
                            channel=str(payload.get("channel", "wechat")).strip() or "wechat",
                            sender=str(payload.get("sender", "")).strip() or None,
                            iterations=int(payload.get("iterations", 3) or 3),
                            warmup=int(payload.get("warmup", 1) or 1),
                        ),
                    )
                    return
                if parsed.path == "/accept-stage6":
                    self._write_json(
                        HTTPStatus.OK,
                        self.server.reply_service.accept_stage6(
                            thread_key=str(payload.get("thread_key", "")).strip() or None,
                            chat_name=str(payload.get("chat_name", "")).strip() or None,
                            channel=str(payload.get("channel", "wechat")).strip() or "wechat",
                            sender=str(payload.get("sender", "")).strip() or None,
                            iterations=int(payload.get("iterations", 3) or 3),
                            warmup=int(payload.get("warmup", 1) or 1),
                        ),
                    )
                    return
                if parsed.path == "/accept-stage7":
                    self._write_json(
                        HTTPStatus.OK,
                        self.server.reply_service.accept_stage7(
                            thread_key=str(payload.get("thread_key", "")).strip() or None,
                            chat_name=str(payload.get("chat_name", "")).strip() or None,
                            channel=str(payload.get("channel", "wechat")).strip() or "wechat",
                            sender=str(payload.get("sender", "")).strip() or None,
                            iterations=int(payload.get("iterations", 3) or 3),
                            warmup=int(payload.get("warmup", 1) or 1),
                        ),
                    )
                    return
                if parsed.path == "/accept-stage8":
                    self._write_json(
                        HTTPStatus.OK,
                        self.server.reply_service.accept_stage8(
                            thread_key=str(payload.get("thread_key", "")).strip() or None,
                            chat_name=str(payload.get("chat_name", "")).strip() or None,
                            channel=str(payload.get("channel", "wechat")).strip() or "wechat",
                            sender=str(payload.get("sender", "")).strip() or None,
                            iterations=int(payload.get("iterations", 3) or 3),
                            warmup=int(payload.get("warmup", 1) or 1),
                        ),
                    )
                    return
                if parsed.path == "/accept-stage9":
                    self._write_json(
                        HTTPStatus.OK,
                        self.server.reply_service.accept_stage9(
                            thread_key=str(payload.get("thread_key", "")).strip() or None,
                            chat_name=str(payload.get("chat_name", "")).strip() or None,
                            channel=str(payload.get("channel", "wechat")).strip() or "wechat",
                            sender=str(payload.get("sender", "")).strip() or None,
                            iterations=int(payload.get("iterations", 3) or 3),
                            warmup=int(payload.get("warmup", 1) or 1),
                        ),
                    )
                    return
            except ValueError as exc:
                self._write_json(HTTPStatus.BAD_REQUEST, {"error": "bad_request", "detail": str(exc)})
                return
            except Exception as exc:  # noqa: BLE001
                self.server.reply_service.logger.exception("reply api request failed")
                self._write_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "server_error", "detail": str(exc)})
                return
            self._write_json(HTTPStatus.NOT_FOUND, {"error": "not_found"})

        def _read_json(self) -> dict[str, Any]:
            raw_length = self.headers.get("Content-Length", "0")
            length = int(raw_length) if raw_length.isdigit() else 0
            body = self.rfile.read(length).decode("utf-8") if length else "{}"
            if not body.strip():
                return {}
            data = json.loads(body)
            if not isinstance(data, dict):
                raise ValueError("request body must be a JSON object")
            return data

        def _write_json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
            encoded = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
            self.send_response(status.value)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

    return Handler


def run_reply_api(config_path: str | None = None, *, host: str | None = None, port: int | None = None) -> None:
    config = load_config(config_path=config_path)
    bind_host = host or config.runtime.api_bind_host
    bind_port = port or config.runtime.api_port
    service = HoloReplyService(config)
    service.logger.info("starting reply api on %s:%s", bind_host, bind_port)
    server = _ReplyHTTPServer((bind_host, bind_port), _handler_factory(), service=service)
    try:
        server.serve_forever()
    finally:
        server.server_close()
