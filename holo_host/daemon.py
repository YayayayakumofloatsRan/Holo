from __future__ import annotations

import json
import logging
import re
import signal
import time
from pathlib import Path
from typing import Any

from .common import atomic_write_text, compact_text, stable_digest, utc_now
from .config import HostConfig, load_config
from .codex_runner import CodexRunner
from .mail_gateway import MailGateway, build_mail_gateway
from .memory_bridge import MemoryBridge, stream_cadences_from_config
from .models import IncomingMessage, OutgoingMessage
from .policy import AutonomyPolicy
from .reply_api import shape_wechat_reply
from .store import QueueStore


def _build_logger(log_dir: Path) -> logging.Logger:
    log_dir.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("holo_host")
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    file_handler = logging.FileHandler(log_dir / "daemon.log", encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)
    return logger


def render_thread_summary(history: list[dict[str, Any]]) -> str:
    if not history:
        return "- 这是这个线程里的第一封信。"
    lines: list[str] = []
    for item in history[-6:]:
        direction = "来信" if item.get("direction") == "inbound" else "回信"
        body = compact_text(str(item.get("body_text", "")), 120)
        created = str(item.get("created_at", ""))
        lines.append(f"- {direction} | {created} | {body}")
    return "\n".join(lines)


def reply_prompt(bundle: dict[str, Any], sidecar: dict[str, Any], *, proactive: bool = False) -> str:
    thread = bundle["thread"]
    contact = bundle["contact"]
    message = bundle.get("message")
    history = render_thread_summary(bundle["history"])
    if proactive:
        reason = bundle["payload"].get("reason", "follow_up")
        user_turn = f"[proactive_followup] reason={reason}"
        body = (
            f"{sidecar['addendum']}\n\n"
            "你现在要给一个已经存在的邮件线程发一封简短跟进信。\n"
            "只输出邮件正文，不要写主题、签名、标题，也不要提自动化、系统、记忆库。\n"
            f"联系人：{contact['display_name'] or contact['email']}\n"
            f"线程主题：{thread['subject']}\n"
            f"历史摘要：\n{history}\n\n"
            f"触发原因：{reason}\n"
            "要求：温和、自然、像旧日商旅在路上偶尔回头问一句近况；不要咄咄逼人。"
        )
        return body

    assert message is not None
    user_turn = str(message["body_text"])
    body = (
        f"{sidecar['addendum']}\n\n"
        "你正在回复一封邮件。\n"
        "只输出邮件正文，不要写主题、签名、标题，也不要提自动化、系统、记忆库。\n"
        f"联系人：{contact['display_name'] or contact['email']}\n"
        f"当前主题：{message['subject']}\n"
        f"线程摘要：\n{history}\n\n"
        f"当前来信：\n{user_turn}\n\n"
        "要求：先真正回应对方，再给建议；若对方疲惫或有压力，先减轻压迫感。"
    )
    return body


def _helper_to_path(raw: str) -> Path:
    if re.match(r"^[A-Za-z]:[\\/]", raw):
        drive = raw[0].lower()
        tail = raw[2:].lstrip("\\/")
        return Path("/mnt") / drive / tail.replace("\\", "/")
    return Path(raw)


def _default_wechat_helper_candidates(repo_root: Path, explicit_path: str = "") -> list[Path]:
    candidates: list[Path] = []
    if explicit_path.strip():
        candidates.append(Path(explicit_path).expanduser())
    candidates.extend(
        [
            repo_root / "windows_helper" / "wechat_helper.live.json",
            repo_root / "windows_helper" / "wechat_helper.example.json",
            _helper_to_path("C:/wechat-helper/wechat_helper.live.json"),
            _helper_to_path("C:/wechat-helper/wechat_helper.json"),
        ]
    )
    return candidates


def load_wechat_helper_settings(repo_root: Path, explicit_path: str = "") -> dict[str, Any]:
    for candidate in _default_wechat_helper_candidates(repo_root, explicit_path):
        if not candidate.exists():
            continue
        try:
            payload = json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        send_queue_raw = str(payload.get("send_queue_dir", "") or "").strip()
        process_path = str(payload.get("pywinauto_process_path", "") or "").strip()
        return {
            "config_path": str(candidate),
            "send_queue_dir": _helper_to_path(send_queue_raw) if send_queue_raw else None,
            "process_path": process_path,
            "whitelist": [str(item).strip() for item in payload.get("whitelist", []) if str(item).strip()],
        }
    return {
        "config_path": "",
        "send_queue_dir": None,
        "process_path": "",
        "whitelist": [],
    }


def initiative_prompt(bundle: dict[str, Any], sidecar: dict[str, Any]) -> str:
    thread = bundle["thread"]
    contact = bundle["contact"]
    history = render_thread_summary(bundle["history"])
    payload = bundle["payload"]
    reason = str(payload.get("reason", "旧线头还挂着"))
    prompt_seed = str(payload.get("prompt", "")).strip()
    return (
        f"{sidecar['addendum']}\n\n"
        "你现在要主动给一个熟悉的微信联系人发一句短消息。\n"
        "只输出最终要发送的聊天正文，不要解释原因，不要提自动化、系统、记忆库。\n"
        f"聊天名：{contact.get('display_name') or thread.get('subject') or thread.get('thread_key')}\n"
        f"线程键：{thread['thread_key']}\n"
        f"最近历史：\n{history}\n\n"
        f"当前想起的原因：{reason}\n"
        f"可借来起话的线头：{prompt_seed or '顺手碰一下近况'}\n"
        "要求：像熟人之间没事找事地轻轻碰一下，不要逼问，不要长篇解释。默认 1 句，最多 2 句。"
    )


class HoloDaemon:
    def __init__(
        self,
        config: HostConfig,
        *,
        store: QueueStore | None = None,
        gateway: MailGateway | None = None,
        runner: CodexRunner | None = None,
        memory: MemoryBridge | None = None,
        policy: AutonomyPolicy | None = None,
        logger: logging.Logger | None = None,
    ):
        self.config = config
        self.store = store or QueueStore(config.runtime.db_path)
        self.store.initialize()
        self.gateway = gateway or build_mail_gateway(config)
        self.runner = runner or CodexRunner(config)
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
        self.logger = logger or _build_logger(config.runtime.log_dir)
        self._stop = False
        self._last_promote_at = 0.0
        self._last_think_at = 0.0
        self._last_reflect_at = 0.0
        self._last_dream_at = 0.0
        self._last_initiative_at = 0.0
        self._wechat_helper_settings: dict[str, Any] | None = None
        signal.signal(signal.SIGTERM, self._signal_stop)
        signal.signal(signal.SIGINT, self._signal_stop)

    def _signal_stop(self, *_args: Any) -> None:
        self._stop = True

    def _wechat_settings(self) -> dict[str, Any]:
        if self._wechat_helper_settings is None:
            self._wechat_helper_settings = load_wechat_helper_settings(
                self.config.runtime.repo_root,
                self.config.autonomy.wechat_helper_config_path,
            )
        return self._wechat_helper_settings

    def _is_whitelisted_initiative_contact(self, chat_name: str) -> bool:
        if not self.config.autonomy.allow_initiative_whitelist_contacts:
            return False
        whitelist = {item.strip() for item in self._wechat_settings().get("whitelist", []) if item.strip()}
        if not whitelist:
            return False
        return chat_name.strip() in whitelist

    def _queue_wechat_send_task(self, *, chat_name: str, text: str, task_id: str) -> dict[str, Any]:
        settings = self._wechat_settings()
        send_queue_dir = settings.get("send_queue_dir")
        if not isinstance(send_queue_dir, Path):
            raise RuntimeError("wechat_send_queue_unavailable")
        payload = {
            "task_id": task_id,
            "chat_name": chat_name,
            "search": chat_name,
            "text": text,
            "created_at": int(time.time()),
            "process_path": str(settings.get("process_path", "") or ""),
        }
        target = send_queue_dir / f"{task_id}.json"
        atomic_write_text(target, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
        return {"path": str(target), "task": payload}

    def run_forever(self) -> None:
        self.logger.info("holo_host daemon started")
        while not self._stop:
            self.run_cycle()
            time.sleep(self.config.runtime.poll_interval_seconds)
        self.logger.info("holo_host daemon stopped")

    def run_cycle(self) -> dict[str, Any]:
        ingested = self._ingest_messages()
        proactive = []
        if self.config.autonomy.allow_proactive_existing_threads:
            proactive = self.store.schedule_due_followups(
                self.config.autonomy.proactive_after_hours,
                limit=max(self.config.runtime.max_jobs_per_cycle, 4),
            )
        think = self._maybe_run_think_cycle()
        reflect = self._maybe_run_reflect_cycle()
        dream = self._maybe_run_dream_cycle()
        initiative = self._maybe_run_initiative_cycle()
        processed = self._process_jobs(self.config.runtime.max_jobs_per_cycle)
        promoted = self._maybe_promote_candidates()
        return {
            "ingested": ingested,
            "scheduled_followups": proactive,
            "think": think,
            "reflect": reflect,
            "dream": dream,
            "initiative": initiative,
            "processed_jobs": processed,
            "promotion": promoted,
        }

    def _ingest_messages(self) -> list[str]:
        results: list[str] = []
        for message in self.gateway.poll_inbox(self.config.mail.poll_limit):
            decision = self.policy.incoming_decision(message)
            record = self.store.record_inbound(message)
            if record.get("duplicate"):
                self.gateway.acknowledge(message)
                results.append(f"duplicate:{message.message_id}")
                continue
            stored_message = record["message"]
            self.store.enqueue_job(
                task_type="reply",
                priority=decision.priority,
                message_row_id=int(stored_message["id"]),
                thread_id=int(record["thread"]["id"]),
                contact_id=int(record["contact"]["id"]),
                payload={"source": "incoming_mail", "risk_tags": decision.risk_tags},
            )
            self.gateway.acknowledge(message)
            results.append(f"queued:{message.message_id}")
        return results

    def _process_jobs(self, limit: int) -> list[str]:
        reports: list[str] = []
        for job in self.store.list_due_jobs(limit=limit):
            job_id = int(job["id"])
            if not self.store.claim_job(job_id):
                continue
            bundle = self.store.get_thread_bundle(job_id, history_limit=self.config.memory.history_messages)
            if not bundle:
                self.store.block_job(job_id, "missing_bundle")
                reports.append(f"blocked:{job_id}:missing_bundle")
                continue
            try:
                if job["task_type"] == "reply":
                    reports.append(self._handle_reply_job(bundle))
                elif job["task_type"] == "proactive_followup":
                    reports.append(self._handle_proactive_job(bundle))
                elif job["task_type"] == "initiative_ping":
                    reports.append(self._handle_initiative_job(bundle))
                else:
                    self.store.block_job(job_id, "unknown_task")
                    reports.append(f"blocked:{job_id}:unknown_task")
            except Exception as exc:  # noqa: BLE001
                self.store.retry_job(job_id, str(exc), delay_seconds=300)
                reports.append(f"retry:{job_id}:{exc}")
                self.logger.exception("job %s failed", job_id)
        return reports

    def _handle_reply_job(self, bundle: dict[str, Any]) -> str:
        job = bundle["job"]
        message = bundle["message"]
        thread = bundle["thread"]
        contact = bundle["contact"]
        user_text = str(message["body_text"])
        sidecar = self.memory.sidecar_packet(
            user_text,
            context={
                "channel": str(thread.get("channel") or message.get("channel") or "email"),
                "thread_key": str(thread.get("thread_key") or ""),
                "chat_name": str(thread.get("subject") or contact.get("display_name") or ""),
                "sender": str(message.get("sender_name") or contact.get("display_name") or ""),
                "contact_display_name": str(contact.get("display_name") or ""),
                "recent_history": bundle.get("history", []),
                "recall_trigger_mode": self.config.memory.recall_trigger_mode,
                "mind_budget": {
                    "fast_history_messages": self.config.memory.fast_history_messages,
                    "recall_history_messages": self.config.memory.recall_history_messages,
                    "fast_episodic_k": self.config.memory.fast_episodic_k,
                    "recall_episodic_k": self.config.memory.recall_episodic_k,
                    "fast_consciousness_k": self.config.memory.fast_consciousness_k,
                    "recall_consciousness_k": self.config.memory.recall_consciousness_k,
                },
            },
        )
        prompt = reply_prompt(bundle, sidecar, proactive=False)
        codex_result = self.runner.run(prompt, session_id=str(thread.get("codex_session_id", "")))
        if codex_result.returncode != 0 or not codex_result.reply_text.strip():
            self.store.retry_job(int(job["id"]), codex_result.stderr or codex_result.stdout or "empty_reply", delay_seconds=300)
            return f"retry:{job['id']}:codex_failure"

        self.store.update_thread_session(int(thread["id"]), codex_result.session_id)
        repaired = self.memory.repair_reply(user_text, codex_result.reply_text)
        final_reply = str(repaired.get("final_draft", codex_result.reply_text)).strip()
        decision = self.policy.outbound_decision(
            incoming_text=user_text,
            reply_text=final_reply,
            recent_outbound_count=self.store.count_recent_outbound(int(contact["id"])),
            is_existing_thread=True,
            is_proactive=False,
        )
        if not decision.allowed:
            self.store.block_job(int(job["id"]), decision.reason)
            return f"blocked:{job['id']}:{decision.reason}"

        outgoing = OutgoingMessage(
            recipient_email=str(message.get("sender_email") or contact["email"]),
            recipient_name=str(message.get("sender_name") or contact.get("display_name") or ""),
            subject=str(message.get("subject") or thread.get("subject") or ""),
            body_text=final_reply,
            thread_key=str(thread["thread_key"]),
            in_reply_to=str(message.get("message_id") or ""),
            references=[part for part in str(message.get("references_header") or "").split() if part],
            metadata={
                "job_id": int(job["id"]),
                "codex_session_id": codex_result.session_id,
                "reply_loop_outcome": repaired.get("outcome", ""),
            },
        )
        remote_message_id = self.gateway.send_reply(outgoing)
        self.store.record_outbound(
            thread_id=int(thread["id"]),
            contact_id=int(contact["id"]),
            remote_message_id=remote_message_id,
            outgoing=outgoing,
        )
        self.memory.record_recall(list(sidecar.get("selected_memory_ids", [])), success=True)
        archive_metadata = {
            "channel": "email",
            "thread_key": str(thread["thread_key"]),
            "message_id": str(message.get("message_id") or ""),
            "outbound_message_id": remote_message_id,
            "sender_email": str(message.get("sender_email") or ""),
            "sender_name": str(message.get("sender_name") or ""),
            "sender": str(message.get("sender_name") or message.get("sender_email") or ""),
            "subject": str(message.get("subject") or ""),
            "chat_name": str(contact.get("display_name") or message.get("sender_name") or message.get("sender_email") or ""),
            "codex_session_id": codex_result.session_id,
            "mind_tier": str(sidecar.get("tier", "")),
            "recall_reason": str(sidecar.get("recall_reason", "")),
            "selected_memory_ids": list(sidecar.get("selected_memory_ids", [])),
        }
        if self.config.memory.auto_observe:
            self.memory.observe_turn(
                user_text,
                final_reply,
                source="holo_host.mail",
                tags=["email", "auto_reply"],
                turn_id=str(message.get("message_id") or ""),
                metadata=archive_metadata,
            )
        else:
            self.memory.archive_turn(
                user_text,
                final_reply,
                source="holo_host.mail",
                tags=["email", "auto_reply"],
                turn_id=str(message.get("message_id") or ""),
                metadata=archive_metadata,
            )
        self.store.complete_job(int(job["id"]), status="sent", sent_message_id=remote_message_id)
        return f"sent:{job['id']}:{remote_message_id}"

    def _handle_proactive_job(self, bundle: dict[str, Any]) -> str:
        job = bundle["job"]
        thread = bundle["thread"]
        contact = bundle["contact"]
        decision = self.policy.outbound_decision(
            incoming_text=str(bundle["payload"]),
            reply_text="proactive_followup",
            recent_outbound_count=self.store.count_recent_outbound(int(contact["id"])),
            is_existing_thread=True,
            is_proactive=True,
        )
        if not decision.allowed:
            self.store.block_job(int(job["id"]), decision.reason)
            return f"blocked:{job['id']}:{decision.reason}"

        pseudo_query = f"请跟进这段沉寂已久的邮件线程。原因：{bundle['payload'].get('reason', 'follow_up')}"
        sidecar = self.memory.sidecar_packet(
            pseudo_query,
            context={
                "channel": str(thread.get("channel") or "email"),
                "thread_key": str(thread.get("thread_key") or ""),
                "chat_name": str(thread.get("subject") or contact.get("display_name") or ""),
                "contact_display_name": str(contact.get("display_name") or ""),
                "recent_history": bundle.get("history", []),
                "recall_trigger_mode": self.config.memory.recall_trigger_mode,
                "mind_budget": {
                    "fast_history_messages": self.config.memory.fast_history_messages,
                    "recall_history_messages": self.config.memory.recall_history_messages,
                    "fast_episodic_k": self.config.memory.fast_episodic_k,
                    "recall_episodic_k": self.config.memory.recall_episodic_k,
                    "fast_consciousness_k": self.config.memory.fast_consciousness_k,
                    "recall_consciousness_k": self.config.memory.recall_consciousness_k,
                },
            },
        )
        prompt = reply_prompt(bundle, sidecar, proactive=True)
        codex_result = self.runner.run(prompt, session_id=str(thread.get("codex_session_id", "")))
        if codex_result.returncode != 0 or not codex_result.reply_text.strip():
            self.store.retry_job(int(job["id"]), codex_result.stderr or codex_result.stdout or "empty_reply", delay_seconds=900)
            return f"retry:{job['id']}:codex_failure"
        final_reply = str(codex_result.reply_text).strip()
        outgoing = OutgoingMessage(
            recipient_email=str(contact["email"]),
            recipient_name=str(contact.get("display_name") or ""),
            subject=str(thread.get("subject") or ""),
            body_text=final_reply,
            thread_key=str(thread["thread_key"]),
            metadata={"job_id": int(job["id"]), "proactive": True, "codex_session_id": codex_result.session_id},
        )
        remote_message_id = self.gateway.send_reply(outgoing)
        self.store.update_thread_session(int(thread["id"]), codex_result.session_id)
        self.store.record_outbound(
            thread_id=int(thread["id"]),
            contact_id=int(contact["id"]),
            remote_message_id=remote_message_id,
            outgoing=outgoing,
        )
        self.memory.record_recall(list(sidecar.get("selected_memory_ids", [])), success=True)
        pseudo_turn = f"[proactive_followup] reason={bundle['payload'].get('reason', 'follow_up')}"
        archive_metadata = {
            "channel": "email",
            "thread_key": str(thread["thread_key"]),
            "message_id": "",
            "outbound_message_id": remote_message_id,
            "sender_email": str(contact.get("email") or ""),
            "sender": str(contact.get("display_name") or contact.get("email") or ""),
            "subject": str(thread.get("subject") or ""),
            "chat_name": str(contact.get("display_name") or contact.get("email") or ""),
            "codex_session_id": codex_result.session_id,
            "proactive": True,
            "reason": str(bundle["payload"].get("reason", "follow_up")),
            "mind_tier": str(sidecar.get("tier", "")),
            "recall_reason": str(sidecar.get("recall_reason", "")),
            "selected_memory_ids": list(sidecar.get("selected_memory_ids", [])),
        }
        if self.config.memory.auto_observe:
            self.memory.observe_turn(
                pseudo_turn,
                final_reply,
                source="holo_host.mail.proactive",
                tags=["email", "proactive_followup"],
                turn_id=f"proactive:{job['id']}",
                metadata=archive_metadata,
            )
        else:
            self.memory.archive_turn(
                pseudo_turn,
                final_reply,
                source="holo_host.mail.proactive",
                tags=["email", "proactive_followup"],
                turn_id=f"proactive:{job['id']}",
                metadata=archive_metadata,
            )
        self.store.complete_job(int(job["id"]), status="queued_transport", sent_message_id=remote_message_id)
        return f"queued:{job['id']}:{remote_message_id}"

    def _handle_initiative_job(self, bundle: dict[str, Any]) -> str:
        job = bundle["job"]
        thread = bundle["thread"]
        contact = bundle["contact"]
        payload = dict(bundle["payload"])
        reason = str(payload.get("reason", "") or payload.get("prompt", "") or "initiative_ping")
        decision = self.policy.outbound_decision(
            incoming_text=reason,
            reply_text="initiative_ping",
            recent_outbound_count=self.store.count_recent_outbound(int(contact["id"])),
            is_existing_thread=True,
            is_proactive=True,
            channel="wechat",
        )
        if not decision.allowed:
            self.store.block_job(int(job["id"]), decision.reason)
            return f"blocked:{job['id']}:{decision.reason}"

        sidecar = self.memory.sidecar_packet(
            reason,
            context={
                "channel": str(thread.get("channel") or payload.get("channel") or "wechat"),
                "thread_key": str(thread.get("thread_key") or payload.get("thread_key") or ""),
                "chat_name": str(payload.get("chat_name") or contact.get("display_name") or thread.get("subject") or ""),
                "contact_display_name": str(contact.get("display_name") or ""),
                "recent_history": bundle.get("history", []),
                "recall_trigger_mode": self.config.memory.recall_trigger_mode,
                "mind_budget": {
                    "fast_history_messages": self.config.memory.fast_history_messages,
                    "recall_history_messages": self.config.memory.recall_history_messages,
                    "fast_episodic_k": self.config.memory.fast_episodic_k,
                    "recall_episodic_k": self.config.memory.recall_episodic_k,
                    "fast_consciousness_k": self.config.memory.fast_consciousness_k,
                    "recall_consciousness_k": self.config.memory.recall_consciousness_k,
                },
            },
        )
        prompt = initiative_prompt(bundle, sidecar)
        codex_result = self.runner.run(prompt, session_id=str(thread.get("codex_session_id", "")))
        if codex_result.returncode != 0 or not codex_result.reply_text.strip():
            self.store.retry_job(int(job["id"]), codex_result.stderr or codex_result.stdout or "empty_reply", delay_seconds=900)
            return f"retry:{job['id']}:codex_failure"

        repaired = self.memory.repair_reply(reason, codex_result.reply_text)
        final_reply = shape_wechat_reply(str(repaired.get("final_draft", codex_result.reply_text)).strip())
        if not final_reply:
            self.store.block_job(int(job["id"]), "empty_initiative_reply")
            return f"blocked:{job['id']}:empty_initiative_reply"

        remote_message_id = f"initiative-wechat-{stable_digest(str(thread['thread_key']), final_reply, str(job['id']))}"
        task_info = self._queue_wechat_send_task(
            chat_name=str(payload.get("chat_name") or contact.get("display_name") or thread.get("subject") or thread.get("thread_key")),
            text=final_reply,
            task_id=remote_message_id,
        )
        outgoing = OutgoingMessage(
            recipient_email=str(contact["email"]),
            recipient_name=str(contact.get("display_name") or ""),
            subject=str(thread.get("subject") or ""),
            body_text=final_reply,
            thread_key=str(thread["thread_key"]),
            channel="wechat",
            metadata={
                "job_id": int(job["id"]),
                "initiative": True,
                "codex_session_id": codex_result.session_id,
                "queue_path": task_info["path"],
            },
        )
        self.store.update_thread_session(int(thread["id"]), codex_result.session_id)
        self.store.record_outbound(
            thread_id=int(thread["id"]),
            contact_id=int(contact["id"]),
            remote_message_id=remote_message_id,
            outgoing=outgoing,
        )
        self.memory.record_recall(list(sidecar.get("selected_memory_ids", [])), success=True)
        self.store.mark_initiative_sent(int(contact["id"]), note=compact_text(reason, 160))
        pseudo_turn = f"[initiative_ping] reason={reason}"
        archive_metadata = {
            "channel": "wechat",
            "thread_key": str(thread["thread_key"]),
            "message_id": "",
            "outbound_message_id": remote_message_id,
            "chat_name": str(payload.get("chat_name") or contact.get("display_name") or ""),
            "sender": str(payload.get("chat_name") or contact.get("display_name") or ""),
            "codex_session_id": codex_result.session_id,
            "initiative": True,
            "reason": reason,
            "queue_path": task_info["path"],
            "mind_tier": str(sidecar.get("tier", "")),
            "recall_reason": str(sidecar.get("recall_reason", "")),
            "selected_memory_ids": list(sidecar.get("selected_memory_ids", [])),
        }
        if self.config.memory.auto_observe:
            self.memory.observe_turn(
                pseudo_turn,
                final_reply,
                source="holo_host.wechat.initiative",
                tags=["wechat", "initiative_ping", "proactive"],
                turn_id=f"initiative:{job['id']}",
                metadata=archive_metadata,
            )
        else:
            self.memory.archive_turn(
                pseudo_turn,
                final_reply,
                source="holo_host.wechat.initiative",
                tags=["wechat", "initiative_ping", "proactive"],
                turn_id=f"initiative:{job['id']}",
                metadata=archive_metadata,
            )
        self.store.complete_job(int(job["id"]), status="queued_transport", sent_message_id=remote_message_id)
        return f"queued:{job['id']}:{remote_message_id}"

    def _maybe_run_think_cycle(self) -> dict[str, Any]:
        now = time.time()
        if now - self._last_think_at < self.config.memory.thought_interval_seconds:
            return {"thought_added": 0, "seed": "", "sampled_archive_ids": []}
        self._last_think_at = now
        result = self.memory.run_think_cycle(sample_size=self.config.memory.thought_sample_size)
        self.memory.record_stream_run("association_stream", status="ok", note="think_cycle", payload=result)
        if result.get("thought_added"):
            self.logger.info(
                "think cycle: seed=%s sampled=%s thought_added=%s",
                result.get("seed", ""),
                ",".join(result.get("sampled_archive_ids", [])),
                result.get("thought_added", 0),
            )
        return result

    def _maybe_run_reflect_cycle(self) -> dict[str, Any]:
        now = time.time()
        if now - self._last_reflect_at < self.config.memory.reflection_interval_seconds:
            return {"candidate_added": 0, "thought_added": 0, "window_hours": self.config.memory.reflection_window_hours}
        self._last_reflect_at = now
        result = self.memory.run_reflect_cycle(window_hours=self.config.memory.reflection_window_hours)
        self.memory.record_stream_run("maintenance_stream", status="ok", note="reflect_cycle", payload=result)
        if result.get("candidate_added") or result.get("thought_added"):
            self.logger.info(
                "reflect cycle: candidate_added=%s thought_added=%s",
                result.get("candidate_added", 0),
                result.get("thought_added", 0),
            )
        return result

    def _maybe_promote_candidates(self) -> dict[str, Any]:
        now = time.time()
        if now - self._last_promote_at < self.config.memory.promote_interval_seconds:
            return {"promoted": [], "skipped": [], "remaining_candidates": None}
        self._last_promote_at = now
        result = self.memory.promote_ready_candidates(limit=self.config.memory.promote_batch_size)
        self.memory.record_stream_run("maintenance_stream", status="ok", note="promote_candidates", payload=result)
        if result["promoted"]:
            self.logger.info("memory promotion: %s", ", ".join(result["promoted"]))
        return result

    def _maybe_run_dream_cycle(self) -> dict[str, Any]:
        now = time.time()
        if now - self._last_dream_at < self.config.memory.dream_interval_seconds:
            return {"sampled_archive_ids": [], "callback_added": 0, "seed": ""}
        self._last_dream_at = now
        result = self.memory.run_dream_cycle(sample_size=self.config.memory.dream_sample_size)
        self.memory.record_stream_run("deep_dream_cycle", status="ok", note="dream_cycle", payload=result)
        if result.get("sampled_archive_ids"):
            self.logger.info(
                "dream cycle: seed=%s sampled=%s callback_added=%s",
                result.get("seed", ""),
                ",".join(result.get("sampled_archive_ids", [])),
                result.get("callback_added", 0),
            )
        return result

    def _maybe_run_initiative_cycle(self) -> dict[str, Any]:
        now = time.time()
        if now - self._last_initiative_at < self.config.memory.initiative_interval_seconds:
            return {"initiative_added": 0, "scheduled_job_ids": []}
        self._last_initiative_at = now
        cycle_report = self.memory.run_initiative_cycle()
        self.memory.record_stream_run("social_stream", status="ok", note="initiative_cycle", payload=cycle_report)
        settings = self._wechat_settings()
        send_queue_dir = settings.get("send_queue_dir")
        if not isinstance(send_queue_dir, Path):
            cycle_report["scheduled_job_ids"] = []
            cycle_report["blocked_reason"] = "wechat_send_queue_unavailable"
            return cycle_report

        scheduled: list[int] = []
        for row in reversed(self.memory.list_initiative_candidates(limit=max(self.config.runtime.max_jobs_per_cycle, 4))):
            channel = str(row.get("channel", "")).strip().lower()
            chat_name = str(row.get("chat_name", "")).strip()
            thread_key = str(row.get("thread_key", "")).strip()
            if channel != "wechat" or not chat_name or not thread_key:
                continue
            if not self._is_whitelisted_initiative_contact(chat_name):
                continue
            contact_email = f"wechat:{thread_key}"
            contact = self.store.find_contact(contact_email) or self.store.ensure_contact(contact_email, chat_name)
            thread = self.store.find_thread(channel="wechat", thread_key=thread_key)
            if thread is None:
                thread, _created = self.store.ensure_thread(
                    channel="wechat",
                    contact_id=int(contact["id"]),
                    thread_key=thread_key,
                    subject=chat_name,
                )
            if not bool(thread.get("allow_proactive", 1)):
                continue
            if not self.store.initiative_available(
                int(contact["id"]),
                cooldown_hours=self.config.autonomy.initiative_cooldown_hours,
            ):
                continue
            if self.store.has_pending_initiative(int(thread["id"])):
                continue
            job_id = self.store.enqueue_job(
                task_type="initiative_ping",
                priority=int(row.get("priority", 55)),
                thread_id=int(thread["id"]),
                contact_id=int(contact["id"]),
                payload=row,
            )
            scheduled.append(job_id)
            if len(scheduled) >= self.config.runtime.max_jobs_per_cycle:
                break
        cycle_report["scheduled_job_ids"] = scheduled
        if scheduled:
            self.logger.info("initiative cycle: staged=%s scheduled=%s", cycle_report.get("initiative_added", 0), ",".join(str(item) for item in scheduled))
        return cycle_report


def build_daemon(config_path: str | None = None) -> HoloDaemon:
    return HoloDaemon(load_config(config_path=config_path))
