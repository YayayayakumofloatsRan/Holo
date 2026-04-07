from __future__ import annotations

import json
import logging
import os
import re
import signal
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .brain_ops import initiative_probe as build_initiative_probe
from .brain_ops import run_self_revision as run_self_revision_cycle
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
    if os.name == "nt":
        return Path(raw)
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


def _parse_utc_timestamp(value: str | None) -> float:
    current = str(value or "").strip()
    if not current:
        return 0.0
    try:
        normalized = current.replace("Z", "+00:00")
        return datetime.fromisoformat(normalized).timestamp()
    except ValueError:
        return 0.0


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

    def brain_mode(self) -> str:
        return str(self.memory.brain_status().get("mode", self.config.memory.brain_mode_default) or self.config.memory.brain_mode_default)

    def set_brain_mode(self, mode: str, *, note: str = "") -> dict[str, Any]:
        return self.memory.set_brain_mode(mode, note=note)

    def brain_status(self) -> dict[str, Any]:
        payload = dict(self.memory.brain_status())
        mode = str(payload.get("mode", self.config.memory.brain_mode_default) or self.config.memory.brain_mode_default)
        latest_activity_at = self.store.latest_activity_at(channel="wechat")
        payload["latest_activity_at"] = latest_activity_at
        payload["idle_seconds"] = max(0.0, time.time() - _parse_utc_timestamp(latest_activity_at))
        loops: list[dict[str, Any]] = []
        seen = {str(item.get("loop_name", "")) for item in payload.get("loops", []) if str(item.get("loop_name", ""))}
        for loop_name, meta in self._loop_definitions(mode).items():
            current = next((dict(item) for item in payload.get("loops", []) if str(item.get("loop_name", "")) == loop_name), {})
            if not current:
                current = {"loop_name": loop_name, "status": "never", "mode": mode, "started_at": "", "finished_at": "", "duration_ms": 0.0, "influence_summary": "", "blocked_reason": "", "next_due_at": ""}
            finished_at = str(current.get("finished_at", "") or current.get("started_at", "") or "")
            next_due_at = current.get("next_due_at")
            if not str(next_due_at or "").strip() and finished_at:
                next_due_at = datetime.fromtimestamp(_parse_utc_timestamp(finished_at) + int(meta["interval_seconds"]), tz=timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
            current["next_due_at"] = str(next_due_at or "")
            loops.append(current)
        for item in payload.get("loops", []):
            if str(item.get("loop_name", "")) not in seen:
                loops.append(dict(item))
        payload["loops"] = sorted(loops, key=lambda item: str(item.get("loop_name", "")))
        return payload

    def _loop_definitions(self, mode: str) -> dict[str, dict[str, Any]]:
        definitions = {
            "heartbeat": {"interval_seconds": max(1, int(self.config.memory.heartbeat_interval_seconds)), "enabled_modes": {"silent", "companion", "dream_only", "full_brain"}},
            "attention_tick": {"interval_seconds": max(1, int(self.config.memory.attention_tick_interval_seconds)), "enabled_modes": {"silent", "companion", "full_brain"}},
            "maintenance_stream": {"interval_seconds": 60, "enabled_modes": {"silent", "companion", "dream_only", "full_brain"}},
            "association_stream": {"interval_seconds": 180, "enabled_modes": {"companion", "full_brain"}},
            "social_stream": {"interval_seconds": 300, "enabled_modes": {"companion", "full_brain"}},
            "deep_dream_cycle": {"interval_seconds": 3600, "enabled_modes": {"dream_only", "full_brain"}},
            "self_revision": {"interval_seconds": max(300, int(self.config.memory.self_revision_interval_seconds)), "enabled_modes": {"companion", "full_brain"}},
        }
        if mode == "full_brain":
            definitions["association_stream"]["interval_seconds"] = max(60, int(definitions["association_stream"]["interval_seconds"] * 0.5))
            definitions["social_stream"]["interval_seconds"] = max(90, int(definitions["social_stream"]["interval_seconds"] * 0.5))
            definitions["self_revision"]["interval_seconds"] = max(600, int(definitions["self_revision"]["interval_seconds"] * 0.5))
        return definitions

    def _loop_due(self, loop_name: str, *, mode: str) -> tuple[bool, str]:
        status = self.memory.brain_status()
        latest = next((dict(item) for item in status.get("loops", []) if str(item.get("loop_name", "")) == loop_name), {})
        interval_seconds = int(self._loop_definitions(mode)[loop_name]["interval_seconds"])
        finished_at = str(latest.get("finished_at", "") or latest.get("started_at", "") or "")
        if not finished_at:
            return True, ""
        due = time.time() - _parse_utc_timestamp(finished_at) >= interval_seconds
        return due, "" if due else "not_due"

    def _record_loop(self, loop_name: str, *, mode: str, started_at: str, started_ts: float, status: str, influence_summary: str = "", blocked_reason: str = "", payload: dict[str, Any] | None = None) -> dict[str, Any]:
        interval_seconds = int(self._loop_definitions(mode)[loop_name]["interval_seconds"])
        next_due = datetime.fromtimestamp(time.time() + interval_seconds, tz=timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        return self.memory.graph.record_brain_loop_run(
            loop_name,
            mode=mode,
            status=status,
            started_at=started_at,
            finished_at=utc_now(),
            duration_ms=round((time.perf_counter() - started_ts) * 1000.0, 2),
            influence_summary=influence_summary,
            blocked_reason=blocked_reason,
            payload=payload,
            next_due_at=next_due,
        )

    def _run_loop(self, loop_name: str, *, mode: str, runner) -> dict[str, Any]:
        definitions = self._loop_definitions(mode)
        if mode not in definitions[loop_name]["enabled_modes"]:
            return {"loop_name": loop_name, "status": "blocked", "blocked_reason": f"mode:{mode}"}
        due, blocked_reason = self._loop_due(loop_name, mode=mode)
        if not due:
            return {"loop_name": loop_name, "status": "idle", "blocked_reason": blocked_reason}
        started_at = utc_now()
        started_ts = time.perf_counter()
        payload = runner()
        payload_dict = payload if isinstance(payload, dict) else {"value": str(payload)}
        status = "ok"
        blocked_reason = ""
        if str(payload_dict.get("status", "")).strip().lower() in {"blocked", "skipped"}:
            status = str(payload_dict.get("status", "")).strip().lower()
            blocked_reason = str(payload_dict.get("blocked_reason", payload_dict.get("reason", "")) or "")
        if isinstance(payload, dict):
            influence_summary = compact_text(
                json.dumps(
                    {
                        "motifs": payload.get("motifs", payload.get("seed", "")),
                        "initiative_added": payload.get("initiative_added", 0),
                        "candidate_added": payload.get("candidate_added", 0),
                        "thought_added": payload.get("thought_added", 0),
                    },
                    ensure_ascii=False,
                ),
                200,
            )
        else:
            influence_summary = compact_text(str(payload), 200)
        record = self._record_loop(
            loop_name,
            mode=mode,
            started_at=started_at,
            started_ts=started_ts,
            status=status,
            influence_summary=influence_summary,
            blocked_reason=blocked_reason,
            payload=payload_dict,
        )
        merged = {"loop_name": loop_name, "result": payload, "record": record}
        if isinstance(payload, dict):
            for key, value in payload.items():
                merged.setdefault(str(key), value)
        return merged

    def run_forever(self) -> None:
        self.logger.info("holo_host daemon started")
        while not self._stop:
            self.run_cycle()
            time.sleep(max(1, min(int(self.config.runtime.poll_interval_seconds), int(self.config.memory.heartbeat_interval_seconds))))
        self.logger.info("holo_host daemon stopped")

    def run_cycle(self) -> dict[str, Any]:
        mode = self.brain_mode()
        latest_activity_at = self.store.latest_activity_at(channel="wechat")
        idle_seconds = max(0.0, time.time() - _parse_utc_timestamp(latest_activity_at))
        self.memory.graph.touch_brain_runtime(
            idle_since=latest_activity_at or utc_now(),
            metadata={"current_mode": mode, "idle_seconds": round(idle_seconds, 2)},
        )
        heartbeat = self._run_loop("heartbeat", mode=mode, runner=lambda: {"status": "alive", "idle_seconds": round(idle_seconds, 2)})
        attention = self._run_loop(
            "attention_tick",
            mode=mode,
            runner=lambda: {
                "latest_activity_at": latest_activity_at,
                "idle_seconds": round(idle_seconds, 2),
                "brain_mode": mode,
            },
        )
        ingested = self._ingest_messages()
        proactive = []
        if self.config.autonomy.allow_proactive_existing_threads:
            proactive = self.store.schedule_due_followups(
                self.config.autonomy.proactive_after_hours,
                limit=max(self.config.runtime.max_jobs_per_cycle, 4),
            )
        maintenance = self._run_loop("maintenance_stream", mode=mode, runner=self._run_maintenance_cycle)
        think = self._run_loop("association_stream", mode=mode, runner=self._run_association_cycle)
        initiative = self._run_loop("social_stream", mode=mode, runner=self._run_social_cycle)
        dream = self._run_loop("deep_dream_cycle", mode=mode, runner=lambda: self._run_deep_dream_cycle(idle_seconds=idle_seconds))
        self_revision = self._run_loop("self_revision", mode=mode, runner=self._run_self_revision_cycle)
        processed = self._process_jobs(self.config.runtime.max_jobs_per_cycle)
        return {
            "mode": mode,
            "heartbeat": heartbeat,
            "attention_tick": attention,
            "ingested": ingested,
            "scheduled_followups": proactive,
            "maintenance": maintenance,
            "think": think,
            "dream": dream,
            "initiative": initiative,
            "self_revision": self_revision,
            "processed_jobs": processed,
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

    def _run_maintenance_cycle(self) -> dict[str, Any]:
        reflect = self.memory.run_reflect_cycle(window_hours=self.config.memory.reflection_window_hours)
        promote = self.memory.promote_ready_candidates(limit=self.config.memory.promote_batch_size)
        payload = {
            "candidate_added": int(reflect.get("candidate_added", 0) or 0),
            "thought_added": int(reflect.get("thought_added", 0) or 0),
            "promoted": list(promote.get("promoted", [])),
            "remaining_candidates": promote.get("remaining_candidates"),
        }
        self.memory.record_stream_run("maintenance_stream", status="ok", note="maintenance_cycle", payload=payload)
        if payload["candidate_added"] or payload["thought_added"] or payload["promoted"]:
            self.logger.info(
                "maintenance cycle: candidate_added=%s thought_added=%s promoted=%s",
                payload["candidate_added"],
                payload["thought_added"],
                ",".join(payload["promoted"]),
            )
        return payload

    def _run_association_cycle(self) -> dict[str, Any]:
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

    def _run_deep_dream_cycle(self, *, idle_seconds: float) -> dict[str, Any]:
        if idle_seconds < float(self.config.memory.dream_idle_threshold_seconds):
            return {"status": "blocked", "blocked_reason": "insufficient_idle_window", "idle_seconds": round(idle_seconds, 2)}
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

    def _run_social_cycle(self) -> dict[str, Any]:
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

    def _run_self_revision_cycle(self) -> dict[str, Any]:
        if not self.config.memory.self_revision_enabled:
            return {"status": "skipped", "reason": "self_revision_disabled"}
        report = run_self_revision_cycle(
            config=self.config,
            runner=self.runner,
            memory=self.memory,
            store=self.store,
            thread_key="Nemoqi",
            chat_name="Nemoqi",
            channel="wechat",
            extra_corrections=["别总这么老成", "不要一直顺着我说", "要有独立性/反身性"],
            apply_patch=True,
        )
        if str(report.get("status", "")) == "applied":
            self.logger.info("self revision applied run_id=%s", report.get("run_id", 0))
        return report

    def initiative_probe(self, *, thread_key: str, chat_name: str, channel: str = "wechat", query: str = "") -> dict[str, Any]:
        return build_initiative_probe(
            config=self.config,
            policy=self.policy,
            memory=self.memory,
            store=self.store,
            thread_key=thread_key,
            chat_name=chat_name,
            channel=channel,
            query=query or "initiative_probe",
        )

    def run_self_revision(
        self,
        *,
        thread_key: str,
        chat_name: str,
        channel: str = "wechat",
        corrections: list[str] | None = None,
        apply_patch: bool = True,
    ) -> dict[str, Any]:
        return run_self_revision_cycle(
            config=self.config,
            runner=self.runner,
            memory=self.memory,
            store=self.store,
            thread_key=thread_key,
            chat_name=chat_name,
            channel=channel,
            extra_corrections=corrections,
            apply_patch=apply_patch,
        )


def build_daemon(config_path: str | None = None) -> HoloDaemon:
    return HoloDaemon(load_config(config_path=config_path))
