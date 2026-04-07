from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import threading
import time
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from pathlib import PureWindowsPath
from typing import Any
from urllib.parse import parse_qs, urlparse

from .capabilities import CapabilityBroker
from .common import atomic_write_text, compact_text, stable_digest
from .config import HostConfig, load_config
from .codex_runner import CodexRunner
from .memory_bridge import MemoryBridge, stream_cadences_from_config
from .models import AttentionState, IncomingMessage, OutgoingMessage, ReplyBubble, TurnContext
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
            vector_backend=config.memory.vector_backend,
            milvus_uri=config.memory.milvus_uri,
            milvus_collection_prefix=config.memory.milvus_collection_prefix,
            activation_cache_enabled=config.memory.activation_cache_enabled,
            private_memory_sync_enabled=config.memory.private_memory_sync_enabled,
            private_memory_repo_path=config.memory.private_memory_repo_path,
        )
        self.policy = policy or AutonomyPolicy(config)
        self.capabilities = CapabilityBroker(config)
        self.logger = logger or _build_logger(config.runtime.log_dir)
        self._memory_lock = threading.RLock()
        self._wechat_history_lock = threading.RLock()
        self._wechat_history_bridge: dict[str, Any] | None = None
        self._wechat_history_state_path = self.config.runtime.state_dir / "active_wechat_history_state.json"

    def health(self) -> dict[str, Any]:
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

    def activation_state(self, *, thread_key: str | None = None, chat_name: str | None = None, channel: str = "wechat") -> dict[str, Any]:
        with self._memory_lock:
            return self.memory.activation_state(thread_key=thread_key, chat_name=chat_name, channel=channel)

    def vector_health(self) -> dict[str, Any]:
        with self._memory_lock:
            return self.memory.vector_health()

    def stream_status(self) -> dict[str, Any]:
        with self._memory_lock:
            return self.memory.stream_status()

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
                "retrieval_trace": dict(packet.get("retrieval_trace", {})),
                "recall_reconstruction": dict((context.mind_packet or {}).get("recall_reconstruction", {})),
                "reply_plan": reply_plan.to_dict(),
            }

        return {
            "chat_name": turn.chat_name,
            "thread_key": incoming.thread_key,
            "channel": turn.channel,
            "query": turn.text,
            "hybrid": _render_probe(hybrid_packet),
            "graph_led": _render_probe(graph_packet),
            "graph": _render_probe(graph_packet),
            "legacy": _render_probe(legacy_packet),
        }

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
            "chat_name": turn.chat_name,
            "sender": turn.sender,
            "contact_display_name": str(contact.get("display_name") or ""),
            "recent_history": history,
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

    def handle_reply(self, payload: dict[str, Any]) -> dict[str, Any]:
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
        sidecar_started_at = time.perf_counter()
        with self._memory_lock:
            sidecar = self.memory.sidecar_packet(turn.text, context=mind_context)
        active_history_report: dict[str, Any] | None = None
        active_history_ms = 0
        if self._should_refresh_wechat_history(turn, sidecar):
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
        capability_started_at = time.perf_counter()
        capability_context = self.capabilities.summarize_turn(turn.text, turn.metadata)
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
    ) -> list[ReplyBubble]:
        raw_bubbles = build_reply_bubbles(
            text,
            channel=channel,
            attention_state=attention_state,
            emotion_state=emotion_state,
            utterance_plan=utterance_plan,
            route=route,
            target_count=target_count,
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
