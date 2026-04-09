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

from .brain_ops import effective_initiative_cooldown_hours
from .brain_ops import initiative_probe as build_initiative_probe
from .brain_ops import run_self_revision as run_self_revision_cycle
from .common import atomic_write_text, compact_text, stable_digest, utc_now
from .config import HostConfig, load_config
from .codex_runner import CodexRunner
from .mail_gateway import MailGateway, build_mail_gateway
from .memory_bridge import MemoryBridge, stream_cadences_from_config
from .mind_graph import MindGraph
from .models import IncomingMessage, OutgoingMessage
from .operator_bus import build_homeostasis_state, operator_probe as run_operator_probe
from .operator_bus import plan_operator_cycle, refresh_self_model, run_operator_cycle
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
        self.runner = runner or CodexRunner(config, usage_recorder=self.store.record_processor_usage)
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

    def _candidate_initiative_confidence(self, row: dict[str, Any]) -> float:
        return float(row.get("initiative_confidence", row.get("override_priority", 0.0)) or 0.0)

    def _candidate_override_hint(self, *, row: dict[str, Any], mode: str) -> bool:
        return (
            str(getattr(self.config.autonomy, "initiative_gate_mode", "conservative") or "conservative").strip().lower() == "adaptive"
            and bool(getattr(self.config.autonomy, "main_brain_override_enabled", True))
            and str(mode or "").strip().lower() == "full_brain"
            and self._candidate_initiative_confidence(row) >= float(getattr(self.config.autonomy, "main_brain_override_min_score", 0.58) or 0.58)
        )

    def _initiative_recent_negative_feedback(self, *, thread_key: str, chat_name: str, channel: str = "wechat") -> bool:
        subject_state = self.memory.graph.subject_state(thread_key=thread_key, chat_name=chat_name, channel=channel)
        outcome_memory = dict(subject_state.get("outcome_memory", {}))
        return bool(outcome_memory.get("was_ignored")) or float(outcome_memory.get("future_initiative_bias", 0.5) or 0.5) < 0.35

    @staticmethod
    def _parse_timestamp(raw: Any) -> datetime | None:
        text = str(raw or "").strip()
        if not text:
            return None
        try:
            return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(timezone.utc)
        except ValueError:
            return None

    @staticmethod
    def _correction_count(messages: list[dict[str, Any]]) -> int:
        markers = ("不要", "别", "不是", "错", "wrong", "don't", "do not", "stop")
        count = 0
        for item in messages:
            body = str(item.get("body_text", "") or "").lower()
            if any(marker in body for marker in markers):
                count += 1
        return count

    @classmethod
    def _derive_action_outcome_from_evidence(
        cls,
        *,
        sent_at: Any,
        recent_messages: list[dict[str, Any]],
        predicted_outcome: dict[str, Any] | None = None,
        usage_total_tokens: int = 0,
        usage_rows: list[dict[str, Any]] | None = None,
        usage_evidence_refs: list[str] | None = None,
    ) -> dict[str, Any]:
        sent_dt = cls._parse_timestamp(sent_at) or datetime.now(timezone.utc)
        inbound_after = [
            dict(item)
            for item in recent_messages
            if str(item.get("direction", "")).strip() == "inbound"
            and (cls._parse_timestamp(item.get("created_at")) or sent_dt) >= sent_dt
        ]
        outbound_after = [
            dict(item)
            for item in recent_messages
            if str(item.get("direction", "")).strip() == "outbound"
            and (cls._parse_timestamp(item.get("created_at")) or sent_dt) >= sent_dt
        ]
        first_inbound_at = cls._parse_timestamp(inbound_after[0].get("created_at")) if inbound_after else None
        reply_latency_seconds = max(0.0, (first_inbound_at - sent_dt).total_seconds()) if first_inbound_at else -1.0
        initiative_success = 1.0 if inbound_after else 0.0
        was_ignored = 0.0 if inbound_after else 1.0
        correction_count = cls._correction_count(inbound_after[:3])
        rewarding_signals = [initiative_success]
        if inbound_after:
            rewarding_signals.append(min(1.0, len(inbound_after) / 3.0))
        if correction_count:
            rewarding_signals.append(max(0.0, 1.0 - min(1.0, correction_count / 3.0)))
        was_rewarding = round(sum(rewarding_signals) / len(rewarding_signals), 4) if rewarding_signals else 0.0
        relational_delta = round(max(0.0, was_rewarding - (correction_count * 0.12)), 4)
        identity_delta = round(max(0.0, 1.0 - min(1.0, correction_count / max(1, len(inbound_after) or 1))) * 0.18, 4)
        future_initiative_bias = round(max(0.0, was_rewarding - was_ignored * 0.25), 4)
        future_resistance_bias = round(min(1.0, correction_count / 3.0), 4)
        usage_rows = [dict(item) for item in list(usage_rows or [])]
        if usage_rows:
            derived_usage_total = sum(int(item.get("total_tokens", 0) or 0) for item in usage_rows)
            usage_total_tokens = derived_usage_total if derived_usage_total > 0 else max(0, int(usage_total_tokens or 0))
        evidence_refs = [
            "messages:recent_thread",
            "messages:inbound_after_send" if inbound_after else "messages:no_inbound_after_send",
        ]
        if usage_rows:
            usage_ref_items = [str(item).strip() for item in list(usage_evidence_refs or []) if str(item).strip()]
            if not usage_ref_items:
                usage_ref_items = [f"usage:processor_usage:{str(item.get('id', '')).strip()}" for item in usage_rows if str(item.get("id", "")).strip()]
            evidence_refs.extend(usage_ref_items)
        else:
            evidence_refs.append("usage:processor_usage_ledger" if usage_total_tokens else "usage:none")
        if predicted_outcome:
            evidence_refs.append("prediction:selected_outcome")
        return {
            "was_rewarding": was_rewarding,
            "was_ignored": was_ignored,
            "relational_delta": relational_delta,
            "identity_delta": identity_delta,
            "future_initiative_bias": future_initiative_bias,
            "future_resistance_bias": future_resistance_bias,
            "reply_latency_seconds": round(reply_latency_seconds, 4) if reply_latency_seconds >= 0.0 else None,
            "initiative_success": initiative_success,
            "correction_count": correction_count,
            "usage_total_tokens": max(0, int(usage_total_tokens or 0)),
            "usage_rows": usage_rows,
            "usage_evidence_refs": evidence_refs,
            "predicted_outcome": dict(predicted_outcome or {}),
            "evidence_refs": evidence_refs,
            "message_counts": {
                "inbound_after": len(inbound_after),
                "outbound_after": len(outbound_after),
            },
        }

    @staticmethod
    def _initiative_probe_block_reason(probe: dict[str, Any]) -> str:
        reasons = list(probe.get("hard_block_reasons", []))
        return str(
            probe.get("blocked_reason_code")
            or (reasons[0] if reasons else "")
            or probe.get("cooldown_rationale", {}).get("reason")
            or probe.get("policy_rationale", {}).get("reason")
            or "initiative_probe_blocked"
        )

    def _can_apply_main_brain_override(self, *, row: dict[str, Any], probe: dict[str, Any], mode: str) -> bool:
        return (
            self._candidate_override_hint(row=row, mode=mode)
            and str(probe.get("gate_level", "")).strip() == "soft_block"
            and bool(probe.get("override_eligible", False))
            and float(probe.get("soft_gate_score", 0.0) or 0.0) >= float(getattr(self.config.autonomy, "initiative_soft_override_floor", 0.48) or 0.48)
        )

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
            "self_model_refresh": {"interval_seconds": max(60, int(self.config.memory.self_model_refresh_interval_seconds)), "enabled_modes": {"companion", "dream_only", "full_brain"}},
            "homeostasis_tick": {"interval_seconds": max(30, int(self.config.memory.homeostasis_tick_interval_seconds)), "enabled_modes": {"silent", "companion", "dream_only", "full_brain"}},
            "affect_tick": {"interval_seconds": max(30, int(self.config.memory.affect_tick_interval_seconds)), "enabled_modes": {"companion", "full_brain"}},
            "drive_arbitration": {"interval_seconds": max(45, int(self.config.memory.drive_arbitration_interval_seconds)), "enabled_modes": {"companion", "full_brain"}},
            "initiative_marketplace": {"interval_seconds": max(60, int(self.config.memory.initiative_marketplace_interval_seconds)), "enabled_modes": {"companion", "full_brain"}},
            "outcome_appraisal": {"interval_seconds": max(90, int(self.config.memory.outcome_appraisal_interval_seconds)), "enabled_modes": {"companion", "full_brain"}},
            "deep_simulation": {"interval_seconds": 420, "enabled_modes": {"companion", "full_brain"}},
            "autobiographical_consolidation": {"interval_seconds": max(120, int(self.config.memory.autobiographical_consolidation_interval_seconds)), "enabled_modes": {"companion", "dream_only", "full_brain"}},
            "goal_arbitration": {"interval_seconds": max(120, int(self.config.memory.goal_arbitration_interval_seconds)), "enabled_modes": {"companion", "full_brain"}},
            "continuity_audit": {"interval_seconds": max(90, int(self.config.memory.continuity_audit_interval_seconds)), "enabled_modes": {"companion", "dream_only", "full_brain"}},
            "operator_planning": {"interval_seconds": max(120, int(self.config.memory.operator_planning_interval_seconds)), "enabled_modes": {"companion", "full_brain"}},
            "operator_shadow_cycle": {"interval_seconds": max(90, int(self.config.memory.operator_shadow_cycle_interval_seconds)), "enabled_modes": {"companion", "full_brain"}},
            "visual_ingest_cycle": {"interval_seconds": max(15, int(self.config.memory.visual_ingest_cycle_interval_seconds)), "enabled_modes": {"silent", "companion", "dream_only", "full_brain"}},
        }
        if mode == "full_brain":
            definitions["association_stream"]["interval_seconds"] = max(60, int(definitions["association_stream"]["interval_seconds"] * 0.5))
            definitions["social_stream"]["interval_seconds"] = max(90, int(definitions["social_stream"]["interval_seconds"] * 0.5))
            definitions["self_revision"]["interval_seconds"] = max(600, int(definitions["self_revision"]["interval_seconds"] * 0.5))
            definitions["affect_tick"]["interval_seconds"] = max(20, int(definitions["affect_tick"]["interval_seconds"] * 0.75))
            definitions["drive_arbitration"]["interval_seconds"] = max(30, int(definitions["drive_arbitration"]["interval_seconds"] * 0.75))
            definitions["initiative_marketplace"]["interval_seconds"] = max(45, int(definitions["initiative_marketplace"]["interval_seconds"] * 0.75))
            definitions["outcome_appraisal"]["interval_seconds"] = max(60, int(definitions["outcome_appraisal"]["interval_seconds"] * 0.75))
            definitions["deep_simulation"]["interval_seconds"] = max(180, int(definitions["deep_simulation"]["interval_seconds"] * 0.75))
            definitions["autobiographical_consolidation"]["interval_seconds"] = max(90, int(definitions["autobiographical_consolidation"]["interval_seconds"] * 0.75))
            definitions["goal_arbitration"]["interval_seconds"] = max(90, int(definitions["goal_arbitration"]["interval_seconds"] * 0.75))
            definitions["continuity_audit"]["interval_seconds"] = max(60, int(definitions["continuity_audit"]["interval_seconds"] * 0.75))
            definitions["operator_planning"]["interval_seconds"] = max(90, int(definitions["operator_planning"]["interval_seconds"] * 0.75))
            definitions["operator_shadow_cycle"]["interval_seconds"] = max(60, int(definitions["operator_shadow_cycle"]["interval_seconds"] * 0.75))
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
        self_model = self._run_loop("self_model_refresh", mode=mode, runner=self._run_self_model_refresh_cycle)
        homeostasis = self._run_loop("homeostasis_tick", mode=mode, runner=self._run_homeostasis_tick)
        affect_tick = self._run_loop("affect_tick", mode=mode, runner=self._run_affect_tick)
        drive_arbitration = self._run_loop("drive_arbitration", mode=mode, runner=self._run_drive_arbitration)
        initiative_marketplace = self._run_loop("initiative_marketplace", mode=mode, runner=self._run_initiative_marketplace)
        outcome_appraisal = self._run_loop("outcome_appraisal", mode=mode, runner=self._run_outcome_appraisal)
        deep_simulation = self._run_loop("deep_simulation", mode=mode, runner=self._run_deep_simulation)
        autobiographical_consolidation = self._run_loop("autobiographical_consolidation", mode=mode, runner=self._run_autobiographical_consolidation)
        goal_arbitration = self._run_loop("goal_arbitration", mode=mode, runner=self._run_goal_arbitration)
        continuity_audit = self._run_loop("continuity_audit", mode=mode, runner=self._run_continuity_audit)
        operator_plan = self._run_loop("operator_planning", mode=mode, runner=self._run_operator_planning_cycle)
        operator_shadow = self._run_loop("operator_shadow_cycle", mode=mode, runner=self._run_operator_shadow_cycle)
        visual_ingest = self._run_loop("visual_ingest_cycle", mode=mode, runner=self._run_visual_ingest_cycle)
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
            "self_model_refresh": self_model,
            "homeostasis_tick": homeostasis,
            "affect_tick": affect_tick,
            "drive_arbitration": drive_arbitration,
            "initiative_marketplace": initiative_marketplace,
            "outcome_appraisal": outcome_appraisal,
            "deep_simulation": deep_simulation,
            "autobiographical_consolidation": autobiographical_consolidation,
            "goal_arbitration": goal_arbitration,
            "continuity_audit": continuity_audit,
            "operator_planning": operator_plan,
            "operator_shadow_cycle": operator_shadow,
            "visual_ingest_cycle": visual_ingest,
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
                elif job["task_type"] == "deferred_reply":
                    reports.append(self._handle_deferred_reply_job(bundle))
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

    def _handle_deferred_reply_job(self, bundle: dict[str, Any]) -> str:
        from .reply_api import HoloReplyService

        job = bundle["job"]
        message = bundle["message"]
        thread = bundle["thread"]
        contact = bundle["contact"]
        payload = dict(bundle.get("payload") or {})
        service = HoloReplyService(
            self.config,
            store=self.store,
            runner=self.runner,
            memory=self.memory,
            policy=self.policy,
            logger=self.logger,
        )
        result = service.handle_reply(
            {
                "chat_name": str(payload.get("chat_name") or thread.get("subject") or contact.get("display_name") or thread.get("thread_key") or ""),
                "thread_key": str(thread.get("thread_key") or payload.get("thread_key") or ""),
                "channel": str(payload.get("channel") or thread.get("channel") or message.get("channel") or "wechat"),
                "sender": str(payload.get("sender") or message.get("sender_name") or contact.get("display_name") or ""),
                "text": str(message.get("body_text") or ""),
                "message_id": str(message.get("message_id") or ""),
                "metadata": dict(payload.get("metadata") or {}),
            }
        )
        action = str(result.get("action", "") or "")
        if action == "reply":
            self.store.complete_job(int(job["id"]), status="completed", sent_message_id=str(result.get("message_id", "")))
            return f"completed:{job['id']}:reply"
        if action == "silence":
            self.store.complete_job(int(job["id"]), status="silenced", sent_message_id="")
            return f"completed:{job['id']}:silence"
        if action == "defer_reply":
            self.store.complete_job(int(job["id"]), status="rescheduled", sent_message_id="")
            return f"completed:{job['id']}:defer_reply"
        if action == "ignore":
            self.store.complete_job(int(job["id"]), status="ignored", sent_message_id="")
            return f"completed:{job['id']}:ignore"
        self.store.retry_job(int(job["id"]), "deferred_reply_unresolved", delay_seconds=300)
        return f"retry:{job['id']}:deferred_reply_unresolved"

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
        candidate_id = int(payload.get("id", 0) or 0)
        reason = str(payload.get("reason", "") or payload.get("prompt", "") or "initiative_ping")
        mode = self.brain_mode()
        override_hint = self._candidate_override_hint(row=payload, mode=mode)
        recent_negative_feedback = self._initiative_recent_negative_feedback(
            thread_key=str(thread.get("thread_key") or payload.get("thread_key") or ""),
            chat_name=str(payload.get("chat_name") or contact.get("display_name") or thread.get("subject") or ""),
            channel="wechat",
        )
        probe = build_initiative_probe(
            config=self.config,
            policy=self.policy,
            memory=self.memory,
            store=self.store,
            thread_key=str(thread.get("thread_key") or payload.get("thread_key") or ""),
            chat_name=str(payload.get("chat_name") or contact.get("display_name") or thread.get("subject") or ""),
            channel="wechat",
            query=reason,
            mode=mode,
            override_applied=override_hint,
            recent_negative_feedback=recent_negative_feedback,
            ignore_pending_job=True,
        )
        override_applied = self._can_apply_main_brain_override(row=payload, probe=probe, mode=mode)
        if not bool(probe.get("allowed", False)) and not override_applied:
            block_reason = self._initiative_probe_block_reason(probe)
            if candidate_id:
                self.memory.graph.update_initiative_candidate(
                    candidate_id=candidate_id,
                    status="blocked",
                    metadata={"blocked_reason": block_reason, "blocked_reason_code": block_reason, "probe": probe},
                    note=block_reason,
                )
            self.store.block_job(int(job["id"]), block_reason)
            return f"blocked:{job['id']}:initiative_probe_blocked"
        decision = self.policy.outbound_decision(
            incoming_text=reason,
            reply_text="initiative_ping",
            recent_outbound_count=self.store.count_recent_outbound(int(contact["id"])),
            is_existing_thread=True,
            is_proactive=True,
            channel="wechat",
        )
        if not decision.allowed:
            if candidate_id:
                self.memory.graph.update_initiative_candidate(
                    candidate_id=candidate_id,
                    status="blocked",
                    metadata={"blocked_reason": decision.reason},
                    note=decision.reason,
                )
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
            if candidate_id:
                self.memory.graph.update_initiative_candidate(
                    candidate_id=candidate_id,
                    status="blocked",
                    metadata={"blocked_reason": "codex_failure"},
                    note="codex_failure",
                )
            self.store.retry_job(int(job["id"]), codex_result.stderr or codex_result.stdout or "empty_reply", delay_seconds=900)
            return f"retry:{job['id']}:codex_failure"

        repaired = self.memory.repair_reply(reason, codex_result.reply_text)
        final_reply = shape_wechat_reply(str(repaired.get("final_draft", codex_result.reply_text)).strip())
        if not final_reply:
            if candidate_id:
                self.memory.graph.update_initiative_candidate(
                    candidate_id=candidate_id,
                    status="blocked",
                    metadata={"blocked_reason": "empty_initiative_reply"},
                    note="empty_initiative_reply",
                )
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
                "main_brain_override_applied": override_applied,
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
        if candidate_id:
            self.memory.graph.update_initiative_candidate(
                candidate_id=candidate_id,
                status="sent",
                metadata={
                    "remote_message_id": remote_message_id,
                    "queue_path": task_info["path"],
                    "main_brain_override_applied": override_applied,
                    "gate_level": str(probe.get("gate_level", "") or ""),
                    "soft_gate_score": float(probe.get("soft_gate_score", 0.0) or 0.0),
                },
                note="sent",
            )
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
            "main_brain_override_applied": override_applied,
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
        blocked: list[dict[str, Any]] = []
        mode = self.brain_mode()
        for row in reversed(self.memory.list_initiative_candidates(limit=max(self.config.runtime.max_jobs_per_cycle, 4))):
            channel = str(row.get("channel", "")).strip().lower()
            chat_name = str(row.get("chat_name", "")).strip()
            thread_key = str(row.get("thread_key", "")).strip()
            if channel != "wechat" or not chat_name or not thread_key:
                continue
            candidate_id = int(row.get("id", 0) or 0)
            if not bool(row.get("send_allowed", False)):
                if candidate_id:
                    self.memory.graph.update_initiative_candidate(
                        candidate_id=candidate_id,
                        status="blocked",
                        metadata={"blocked_reason": "send_not_allowed", "blocked_reason_code": "send_not_allowed"},
                        note="send_not_allowed",
                    )
                continue
            if not self._is_whitelisted_initiative_contact(chat_name):
                if candidate_id:
                    self.memory.graph.update_initiative_candidate(
                        candidate_id=candidate_id,
                        status="blocked",
                        metadata={"blocked_reason": "not_whitelisted", "blocked_reason_code": "not_whitelisted"},
                        note="not_whitelisted",
                    )
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
                if candidate_id:
                    self.memory.graph.update_initiative_candidate(
                        candidate_id=candidate_id,
                        status="blocked",
                        metadata={"blocked_reason": "thread_proactive_disabled", "blocked_reason_code": "thread_proactive_disabled"},
                        note="thread_proactive_disabled",
                    )
                continue
            override_hint = self._candidate_override_hint(row=row, mode=mode)
            recent_negative_feedback = self._initiative_recent_negative_feedback(
                thread_key=thread_key,
                chat_name=chat_name,
                channel="wechat",
            )
            game_state = self.memory.graph.game_state(thread_key=thread_key, chat_name=chat_name, channel="wechat")
            cooldown_hours = effective_initiative_cooldown_hours(
                config=self.config,
                game_state=game_state,
                mode=mode,
                override_applied=override_hint,
                recent_negative_feedback=recent_negative_feedback,
            )
            if not self.store.initiative_available(
                int(contact["id"]),
                cooldown_hours=cooldown_hours,
            ):
                blocked.append(
                    {
                        "thread_key": thread_key,
                        "chat_name": chat_name,
                        "reason": "cooldown_active",
                        "cooldown_hours": cooldown_hours,
                    }
                )
                if candidate_id:
                    self.memory.graph.update_initiative_candidate(
                        candidate_id=candidate_id,
                        status="blocked",
                        metadata={"blocked_reason": "cooldown_active", "blocked_reason_code": "cooldown_active"},
                        note="cooldown_active",
                    )
                continue
            if self.store.has_pending_initiative(int(thread["id"])):
                blocked.append(
                    {
                        "thread_key": thread_key,
                        "chat_name": chat_name,
                        "reason": "pending_initiative_job",
                    }
                )
                if candidate_id:
                    self.memory.graph.update_initiative_candidate(
                        candidate_id=candidate_id,
                        status="blocked",
                        metadata={"blocked_reason": "pending_initiative_job", "blocked_reason_code": "pending_initiative_job"},
                        note="pending_initiative_job",
                    )
                continue
            probe = build_initiative_probe(
                config=self.config,
                policy=self.policy,
                memory=self.memory,
                store=self.store,
                thread_key=thread_key,
                chat_name=chat_name,
                channel="wechat",
                query=str(row.get("prompt", "") or row.get("reason", "") or "initiative_ping"),
                mode=mode,
                override_applied=override_hint,
                recent_negative_feedback=recent_negative_feedback,
            )
            override_ready = self._can_apply_main_brain_override(row=row, probe=probe, mode=mode)
            if str(probe.get("gate_level", "")).strip() == "hard_block":
                blocked.append(
                    {
                        "thread_key": thread_key,
                        "chat_name": chat_name,
                        "reason": self._initiative_probe_block_reason(probe),
                        "probe": probe,
                    }
                )
                if candidate_id:
                    self.memory.graph.update_initiative_candidate(
                        candidate_id=candidate_id,
                        status="blocked",
                        metadata={"blocked_reason": self._initiative_probe_block_reason(probe), "blocked_reason_code": self._initiative_probe_block_reason(probe), "probe": probe},
                        note=self._initiative_probe_block_reason(probe),
                    )
                continue
            if not bool(probe.get("allowed", False)) and not override_ready:
                blocked.append(
                    {
                        "thread_key": thread_key,
                        "chat_name": chat_name,
                        "reason": str(probe.get("blocked_reason_code", "") or "soft_gate_blocked"),
                        "probe": probe,
                    }
                )
                if candidate_id:
                    self.memory.graph.update_initiative_candidate(
                        candidate_id=candidate_id,
                        status="blocked",
                        metadata={"blocked_reason": str(probe.get("blocked_reason_code", "") or "soft_gate_blocked"), "blocked_reason_code": str(probe.get("blocked_reason_code", "") or "soft_gate_blocked"), "probe": probe},
                        note=str(probe.get("blocked_reason_code", "") or "soft_gate_blocked"),
                    )
                continue
            job_id = self.store.enqueue_job(
                task_type="initiative_ping",
                priority=int(row.get("priority", 55)),
                thread_id=int(thread["id"]),
                contact_id=int(contact["id"]),
                payload={
                    **row,
                    "gate_level": str(probe.get("gate_level", "") or ""),
                    "soft_gate_score": float(probe.get("soft_gate_score", 0.0) or 0.0),
                    "override_eligible": bool(probe.get("override_eligible", False)),
                    "main_brain_override_candidate": override_ready,
                },
            )
            scheduled.append(job_id)
            if candidate_id:
                self.memory.graph.update_initiative_candidate(
                    candidate_id=candidate_id,
                    status="override_pending" if override_ready and not bool(probe.get("allowed", False)) else "scheduled",
                    metadata={
                        "scheduled_job_id": job_id,
                        "gate_level": str(probe.get("gate_level", "") or ""),
                        "soft_gate_score": float(probe.get("soft_gate_score", 0.0) or 0.0),
                        "override_eligible": bool(probe.get("override_eligible", False)),
                        "main_brain_override_candidate": override_ready,
                    },
                    note="override_pending" if override_ready and not bool(probe.get("allowed", False)) else "scheduled",
                )
            if len(scheduled) >= self.config.runtime.max_jobs_per_cycle:
                break
        cycle_report["scheduled_job_ids"] = scheduled
        cycle_report["blocked_candidates"] = blocked
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

    def _run_self_model_refresh_cycle(self) -> dict[str, Any]:
        report = refresh_self_model(
            config=self.config,
            runner=self.runner,
            memory=self.memory,
            store=self.store,
            reason="daemon:self_model_refresh",
            source="daemon",
        )
        self.logger.info("self model refreshed continuity=%s deficits=%s", report.get("identity_continuity", 0.0), ",".join(report.get("active_deficits", [])))
        return report

    def _run_homeostasis_tick(self) -> dict[str, Any]:
        state = build_homeostasis_state(memory=self.memory, config=self.config)
        self.memory.graph.touch_brain_runtime(metadata={"homeostasis_state": state})
        return state

    def _run_affect_tick(self) -> dict[str, Any]:
        updated: list[dict[str, Any]] = []
        for item in self.memory.graph.top_thread_commitments(limit=6):
            channel = str(item.get("channel", "") or "").strip() or "wechat"
            thread_key = str(item.get("thread_key", "") or "").strip()
            chat_name = str(item.get("chat_name", "") or thread_key).strip() or thread_key
            if not thread_key:
                continue
            subject = self.memory.graph.subject_state(thread_key=thread_key, chat_name=chat_name, channel=channel)
            affect = dict(subject.get("affect_state", {}))
            drive = dict(subject.get("drive_state", {}))
            affect["boredom"] = self.memory._clamp(float(affect.get("boredom", 0.0) or 0.0) + 0.03, default=0.0)
            affect["curiosity"] = self.memory._clamp(MindGraph.metric_value(affect.get("curiosity", 0.0), default=0.0) + 0.02, default=0.0)
            affect["attachment_pull"] = self.memory._clamp(MindGraph.metric_value(affect.get("attachment_pull", 0.0), default=0.0) + 0.015, default=0.0)
            drive["seek_contact"] = self.memory._clamp(float(drive.get("seek_contact", 0.0) or 0.0) + 0.02, default=0.0)
            self.memory.graph.update_subject_state(
                channel=channel,
                thread_key=thread_key,
                chat_name=chat_name,
                affect_state=affect,
                drive_state=drive,
                metadata={"affect_tick": utc_now()},
                note="affect_tick",
                source="daemon",
            )
            updated.append({"thread_key": thread_key, "chat_name": chat_name, "boredom": affect["boredom"], "seek_contact": drive["seek_contact"]})
        return {"status": "ok", "updated_threads": len(updated), "threads": updated[:4]}

    def _run_drive_arbitration(self) -> dict[str, Any]:
        updated: list[dict[str, Any]] = []
        for item in self.memory.graph.top_thread_commitments(limit=6):
            channel = str(item.get("channel", "") or "").strip() or "wechat"
            thread_key = str(item.get("thread_key", "") or "").strip()
            chat_name = str(item.get("chat_name", "") or thread_key).strip() or thread_key
            if not thread_key:
                continue
            subject = self.memory.graph.subject_state(thread_key=thread_key, chat_name=chat_name, channel=channel)
            affect = dict(subject.get("affect_state", {}))
            drive = dict(subject.get("drive_state", {}))
            value = dict(subject.get("value_state", {}))
            conflict = dict(subject.get("conflict_state", {}))
            pressure = self.memory._initiative_pressure(affect, drive, value, conflict)
            self.memory.graph.update_subject_state(
                channel=channel,
                thread_key=thread_key,
                chat_name=chat_name,
                initiative_state={"pressure": pressure},
                metadata={"drive_arbitration": utc_now()},
                note="drive_arbitration",
                source="daemon",
            )
            updated.append({"thread_key": thread_key, "chat_name": chat_name, "pressure": pressure})
        return {"status": "ok", "updated_threads": len(updated), "pressure": updated[:4]}

    def _run_initiative_marketplace(self) -> dict[str, Any]:
        return self.memory.run_initiative_cycle(dry_run=False)

    def _run_outcome_appraisal(self) -> dict[str, Any]:
        appraised: list[dict[str, Any]] = []
        for item in self.memory.graph.top_thread_commitments(limit=4):
            channel = str(item.get("channel", "") or "").strip() or "wechat"
            thread_key = str(item.get("thread_key", "") or "").strip()
            chat_name = str(item.get("chat_name", "") or thread_key).strip() or thread_key
            if not thread_key:
                continue
            market = self.memory.graph.list_initiative_market(
                thread_key=thread_key,
                chat_name=chat_name,
                channel=channel,
                limit=3,
                statuses=("sent",),
            )
            if not market:
                continue
            latest = dict(market[0])
            metadata = dict(latest.get("metadata", {}))
            if bool(metadata.get("outcome_appraised", False)):
                continue
            subject = self.memory.graph.subject_state(thread_key=thread_key, chat_name=chat_name, channel=channel)
            world_state = dict(subject.get("world_state", {}))
            predicted_outcome = dict(metadata.get("selected_prediction", {}))
            if not predicted_outcome:
                predicted_outcome = dict(dict(world_state.get("last_counterfactual_summary", {})).get("selected_prediction", {}))
            thread = self.store.find_thread(channel=channel, thread_key=thread_key)
            recent_messages = self.store.recent_thread_messages(int(thread["id"]), limit=12) if thread else []
            usage_rows: list[dict[str, Any]] = []
            usage_evidence_refs: list[str] = []
            event_id = str(metadata.get("event_id", "") or "").strip()
            if event_id:
                usage_rows = self.store._fetchall(
                    """
                    SELECT * FROM processor_usage_ledger
                    WHERE event_id = ?
                    ORDER BY id DESC
                    LIMIT 12
                    """,
                    (event_id,),
                )
                usage_evidence_refs = [f"usage:event_id:{event_id}"]
            elif thread_key:
                usage_rows = self.store._fetchall(
                    """
                    SELECT * FROM processor_usage_ledger
                    WHERE thread_key = ?
                    ORDER BY id DESC
                    LIMIT 12
                    """,
                    (thread_key,),
                )
                usage_evidence_refs = [f"usage:thread_key:{thread_key}"]
            evidence_payload = self._derive_action_outcome_from_evidence(
                sent_at=latest.get("updated_at") or latest.get("created_at"),
                recent_messages=list(reversed(recent_messages)),
                predicted_outcome=predicted_outcome,
                usage_rows=usage_rows,
                usage_evidence_refs=usage_evidence_refs,
            )
            appraisal = self.memory.appraise_outcome(
                channel=channel,
                thread_key=thread_key,
                chat_name=chat_name,
                action_type="initiative_ping",
                action_ref=str(latest.get("id", "")),
                was_rewarding=float(evidence_payload.get("was_rewarding", 0.0) or 0.0),
                was_ignored=float(evidence_payload.get("was_ignored", 0.0) or 0.0),
                relational_delta=float(evidence_payload.get("relational_delta", 0.0) or 0.0),
                identity_delta=float(evidence_payload.get("identity_delta", 0.0) or 0.0),
                future_initiative_bias=float(evidence_payload.get("future_initiative_bias", 0.0) or 0.0),
                future_resistance_bias=float(evidence_payload.get("future_resistance_bias", 0.0) or 0.0),
                metadata={"source_candidate": latest.get("candidate_type", ""), **evidence_payload},
            )
            self.memory.graph.update_initiative_candidate(
                candidate_id=int(latest.get("id", 0) or 0),
                status="sent",
                metadata={"outcome_appraised": True},
                note="outcome_appraised",
            )
            appraised.append({"thread_key": thread_key, "candidate_id": latest.get("id", 0), "outcome": appraisal})
        if not appraised:
            return {"status": "blocked", "blocked_reason": "no_pending_outcome"}
        return {"status": "ok", "appraised": len(appraised), "items": appraised[:3]}

    def _run_deep_simulation(self) -> dict[str, Any]:
        simulated: list[dict[str, Any]] = []
        for item in self.memory.graph.top_thread_commitments(limit=4):
            channel = str(item.get("channel", "") or "").strip() or "wechat"
            thread_key = str(item.get("thread_key", "") or "").strip()
            chat_name = str(item.get("chat_name", "") or thread_key).strip() or thread_key
            if not thread_key:
                continue
            prompt = "how about now"
            unfinished = [str(line).strip() for line in item.get("unfinished_threads", []) if str(line).strip()]
            if unfinished:
                prompt = unfinished[0]
            trace = self.memory.trace_counterfactual(
                query=prompt,
                thread_key=thread_key,
                chat_name=chat_name,
                channel=channel,
                limit=3,
            )
            summary = {
                "query": prompt,
                "selected_action": dict(trace.get("selected_action", {})),
                "selected_prediction": dict(trace.get("selected_prediction", {})),
                "counterfactual_summary": dict(trace.get("counterfactual_summary", {})),
                "at": utc_now(),
            }
            current_world = dict(self.memory.graph.subject_state(thread_key=thread_key, chat_name=chat_name, channel=channel).get("world_state", {}))
            current_world["last_counterfactual_summary"] = summary
            self.memory.graph.update_subject_state(
                channel=channel,
                thread_key=thread_key,
                chat_name=chat_name,
                world_state=current_world,
                metadata={"deep_simulation_at": summary["at"]},
                note="deep_simulation",
                source="daemon",
            )
            simulated.append(
                {
                    "thread_key": thread_key,
                    "chat_name": chat_name,
                    "query": prompt,
                    "selected_action": dict(trace.get("selected_action", {})).get("action_type", ""),
                }
            )
        if not simulated:
            return {"status": "blocked", "blocked_reason": "no_threads_for_simulation"}
        return {"status": "ok", "simulated_threads": len(simulated), "items": simulated[:3]}

    def _run_autobiographical_consolidation(self) -> dict[str, Any]:
        subject = self.memory.graph.subject_state(thread_key="Nemoqi", chat_name="Nemoqi", channel="wechat")
        self_model = self.memory.self_model_state()
        world_state = dict(subject.get("world_state", {}))
        last_action = dict(dict(subject.get("metadata", {})).get("last_selected_action", {}))
        last_action_type = str(last_action.get("action_type", "") or "")
        active_deficits = [str(item).strip() for item in self_model.get("active_deficits", []) if str(item).strip()]
        chapter = "consolidating_continuity"
        if active_deficits:
            chapter = "repairing_edges"
        if last_action_type in {"proactive_ping", "reply_multi"}:
            chapter = "reaching_out"
        explanation = {
            "at": utc_now(),
            "summary": f"recently leaning toward {chapter.replace('_', ' ')} because {last_action_type or 'background consolidation'} and current deficits are shaping the tone.",
            "reason": {
                "last_action": last_action_type,
                "active_deficits": active_deficits,
                "world_response_expectations": dict(world_state.get("response_expectations", {})),
            },
        }
        update = self.memory.graph.update_autobiographical_state(
            {
                "current_chapter": chapter,
                "identity_arc": f"Holo is carrying forward continuity while learning to balance liveliness and restraint during {chapter.replace('_', ' ')}.",
                "recent_changes": [explanation],
                "self_explanations": [explanation],
                "unresolved_tensions": list({*self.memory.graph.autobiographical_state().get("unresolved_tensions", []), *active_deficits}),
                "metadata": {"last_consolidated_at": utc_now(), "source": "daemon"},
            },
            reason="daemon:autobiographical_consolidation",
            source="daemon",
        )
        return {
            "status": "ok",
            "current_chapter": update.get("current_chapter", ""),
            "identity_arc": update.get("identity_arc", ""),
            "recent_changes": list(update.get("recent_changes", []))[-3:],
        }

    def _run_goal_arbitration(self) -> dict[str, Any]:
        current = self.memory.graph.goal_state()
        active_goals = [dict(item) for item in current.get("active_goals", []) if isinstance(item, dict)]
        subject = self.memory.graph.subject_state(thread_key="Nemoqi", chat_name="Nemoqi", channel="wechat")
        self_model = self.memory.self_model_state()
        engineering_snapshot = dict(dict(self_model.get("metadata", {})).get("engineering_snapshot", {}))
        world_state = dict(subject.get("world_state", {}))
        expectations = dict(world_state.get("response_expectations", {}))
        deficits = {str(item).strip() for item in self_model.get("active_deficits", []) if str(item).strip()}
        engineering_deficits = {str(item).strip() for item in engineering_snapshot.get("active_deficits", []) if str(item).strip()}
        budget_pressure = float(engineering_snapshot.get("budget_pressure", 0.0) or 0.0)
        engineering_confidence = float(engineering_snapshot.get("engineering_confidence", 0.0) or 0.0)
        provider_state = dict(engineering_snapshot.get("provider_state", {}))
        routing_state = dict(engineering_snapshot.get("routing_state", {}))
        cache_state = dict(engineering_snapshot.get("cache_state", {}))
        seeded_builder = getattr(self.memory.graph, "_default_goal_state", None)
        if callable(seeded_builder):
            seeded_state = dict(seeded_builder())
        else:
            commitments_source = getattr(self.memory.graph, "top_thread_commitments", None)
            commitments = commitments_source(limit=3) if callable(commitments_source) else []
            now = utc_now()
            seeded_goals: list[dict[str, Any]] = [
                {
                    "goal_id": "identity_maintenance",
                    "goal_type": "identity_maintenance",
                    "summary": "keep Holo coherent, continuous, and not overly stiff",
                    "priority": 0.92,
                    "progress": round(float(self_model.get("identity_continuity", 0.6) or 0.6), 4),
                    "target_thread": "",
                    "evidence": list(deficits)[:2],
                    "last_moved_at": now,
                    "stalled_reason": "",
                },
                {
                    "goal_id": "recall_quality",
                    "goal_type": "recall_quality",
                    "summary": "keep memory recall deep, accurate, and continuity-safe",
                    "priority": 0.78,
                    "progress": 0.52,
                    "target_thread": "",
                    "evidence": ["memory continuity matters"],
                    "last_moved_at": now,
                    "stalled_reason": "",
                },
                {
                    "goal_id": "liveliness_balance",
                    "goal_type": "liveliness_balance",
                    "summary": "stay lively and wolfish without sliding back into stiffness or sprawl",
                    "priority": 0.72,
                    "progress": 0.46,
                    "target_thread": "",
                    "evidence": ["tone balance"],
                    "last_moved_at": now,
                    "stalled_reason": "",
                },
            ]
            if commitments:
                top = dict(commitments[0])
                target_thread = str(top.get("thread_key", "") or "")
                target_name = str(top.get("chat_name", "") or target_thread)
                seeded_goals.extend(
                    [
                        {
                            "goal_id": f"relationship_continuity:{target_thread}",
                            "goal_type": "relationship_continuity",
                            "summary": f"keep continuity alive with {target_name}",
                            "priority": 0.84,
                            "progress": round(float(top.get("relationship_score", 0.0) or 0.0), 4),
                            "target_thread": target_thread,
                            "evidence": [str(top.get("summary", ""))],
                            "last_moved_at": now,
                            "stalled_reason": "",
                        },
                        {
                            "goal_id": f"contact_maintenance:{target_thread}",
                            "goal_type": "contact_maintenance",
                            "summary": f"keep a warm contact window open with {target_name}",
                            "priority": 0.66,
                            "progress": round(min(1.0, float(top.get("relationship_score", 0.0) or 0.0) * 0.82), 4),
                            "target_thread": target_thread,
                            "evidence": [str(top.get("summary", ""))],
                            "last_moved_at": now,
                            "stalled_reason": "",
                        },
                    ]
                )
            if deficits:
                seeded_goals.append(
                    {
                        "goal_id": "self_repair",
                        "goal_type": "self_repair",
                        "summary": "repair the most active deficits without destabilizing identity",
                        "priority": 0.7,
                        "progress": 0.34,
                        "target_thread": "",
                        "evidence": list(deficits)[:3],
                        "last_moved_at": now,
                        "stalled_reason": "",
                    }
                )
            seeded_state = {
                "active_goals": seeded_goals[:6],
                "goal_commitments": [
                    {"summary": str(item).strip(), "source": "self_model"}
                    for item in list(self_model.get("relational_commitments", []))[:4]
                    if str(item).strip()
                ],
                "next_goal_windows": [
                    {
                        "goal_id": str(item.get("goal_id", "")),
                        "target_thread": str(item.get("target_thread", "")),
                        "window": "next_relevant_turn" if str(item.get("target_thread", "")) else "next_internal_cycle",
                    }
                    for item in seeded_goals[:4]
                ],
                "goal_progress": {str(item.get("goal_id", "")): round(float(item.get("progress", 0.0) or 0.0), 4) for item in seeded_goals[:6]},
                "pursuit_bias": {str(item.get("goal_id", "")): round(float(item.get("priority", 0.0) or 0.0), 4) for item in seeded_goals[:6]},
                "abandonment_cost": {str(item.get("goal_id", "")): round(float(item.get("priority", 0.0) or 0.0) * 0.6, 4) for item in seeded_goals[:6]},
                "goal_conflicts": [],
            }
        if not active_goals:
            active_goals = [dict(item) for item in seeded_state.get("active_goals", []) if isinstance(item, dict)]
        goal_by_id = {
            str(goal.get("goal_id", "") or "").strip(): goal
            for goal in active_goals
            if isinstance(goal, dict) and str(goal.get("goal_id", "") or "").strip()
        }

        def _upsert_engineering_goal(
            *,
            goal_id: str,
            goal_type: str,
            summary: str,
            priority: float,
            progress: float,
            evidence: list[str],
            stalled_reason: str,
        ) -> None:
            payload = {
                "goal_id": goal_id,
                "goal_type": goal_type,
                "summary": summary,
                "priority": round(self.memory._clamp(priority, default=0.5), 4),
                "progress": round(self.memory._clamp(progress, default=0.0), 4),
                "target_thread": "",
                "evidence": [str(item).strip() for item in evidence if str(item).strip()][:4],
                "last_moved_at": utc_now(),
                "stalled_reason": stalled_reason,
            }
            existing = goal_by_id.get(goal_id)
            if existing is None:
                active_goals.append(payload)
                goal_by_id[goal_id] = payload
                return
            existing.update(payload)

        if budget_pressure >= 0.24 or {"usage_visibility_cold", "operator_overplanning_risk"} & engineering_deficits:
            _upsert_engineering_goal(
                goal_id="cost_discipline",
                goal_type="cost_discipline",
                summary="keep token burn visible and bounded before adding more background planning",
                priority=0.5 + budget_pressure * 0.22,
                progress=max(0.0, 1.0 - budget_pressure),
                evidence=sorted(engineering_deficits & {"usage_visibility_cold", "operator_overplanning_risk"}) or ["budget_pressure"],
                stalled_reason="" if budget_pressure < 0.3 else "budget_pressure",
            )
        if not bool(provider_state.get("fallback_ready", False)) or list(routing_state.get("routing_gaps", [])):
            _upsert_engineering_goal(
                goal_id="routing_resilience",
                goal_type="routing_resilience",
                summary="keep provider fallback and task routing resilience explicit and bounded",
                priority=0.52 + (0.12 if not bool(provider_state.get("fallback_ready", False)) else 0.0),
                progress=0.34 if not bool(provider_state.get("fallback_ready", False)) else 0.58,
                evidence=sorted(engineering_deficits & {"provider_fallback_unready"}) or list(routing_state.get("routing_gaps", []))[:3],
                stalled_reason="provider_fallback_unready" if not bool(provider_state.get("fallback_ready", False)) else "",
            )
        if {"cache_reuse_weak", "cache_coldness"} & (engineering_deficits | deficits):
            _upsert_engineering_goal(
                goal_id="cache_warmth",
                goal_type="cache_warmth",
                summary="warm reuse before deeper planning or recall-heavy elaboration",
                priority=0.54 + (0.08 if "cache_reuse_weak" in engineering_deficits else 0.0),
                progress=float(cache_state.get("hit_ratio", 0.0) or 0.0),
                evidence=sorted((engineering_deficits | deficits) & {"cache_reuse_weak", "cache_coldness"}) or ["cache_hit_ratio"],
                stalled_reason="cache_reuse_weak" if "cache_reuse_weak" in engineering_deficits else "",
            )
        if {"expression_calibration_gap", "stiffness_drift"} & (engineering_deficits | deficits):
            _upsert_engineering_goal(
                goal_id="expression_calibration",
                goal_type="expression_calibration",
                summary="keep expression self-aware and lightweight without drifting into stiffness",
                priority=0.5 + (0.08 if "expression_calibration_gap" in engineering_deficits else 0.0),
                progress=max(0.0, engineering_confidence - 0.18),
                evidence=sorted((engineering_deficits | deficits) & {"expression_calibration_gap", "stiffness_drift"}),
                stalled_reason="expression_calibration_gap" if "expression_calibration_gap" in engineering_deficits else "",
            )
        goal_commitments = [dict(item) for item in current.get("goal_commitments", []) if isinstance(item, dict)]
        if not goal_commitments:
            goal_commitments = [dict(item) for item in seeded_state.get("goal_commitments", []) if isinstance(item, dict)]
        next_goal_windows = [dict(item) for item in current.get("next_goal_windows", []) if isinstance(item, dict)]
        if not next_goal_windows:
            next_goal_windows = [dict(item) for item in seeded_state.get("next_goal_windows", []) if isinstance(item, dict)]
        priorities = {
            "identity_maintenance": 0.72 + (0.08 if deficits else 0.0),
            "relationship_continuity": 0.76 + MindGraph.metric_value(expectations.get("reply_likelihood", 0.0), default=0.0) * 0.12,
            "recall_quality": 0.68 + (0.06 if "cache_coldness" in deficits else 0.0),
            "liveliness_balance": 0.66 + (0.06 if "stiffness_drift" in deficits else 0.0),
            "self_repair": 0.64 + (0.1 if deficits else 0.0),
            "contact_maintenance": 0.62 + MindGraph.metric_value(expectations.get("initiative_receptivity", 0.0), default=0.0) * 0.1,
            "cost_discipline": 0.48 + budget_pressure * 0.24,
            "routing_resilience": 0.5 + (0.1 if not bool(provider_state.get("fallback_ready", False)) else 0.0),
            "cache_warmth": 0.52 + (0.08 if "cache_reuse_weak" in engineering_deficits else 0.0),
            "expression_calibration": 0.48 + (0.08 if "expression_calibration_gap" in engineering_deficits else 0.0),
        }
        refreshed: list[dict[str, Any]] = []
        goal_progress = dict(current.get("goal_progress", {}))
        pursuit_bias = dict(current.get("pursuit_bias", {}))
        abandonment_cost = dict(current.get("abandonment_cost", {}))
        for goal in active_goals:
            goal_type = str(goal.get("goal_type", "") or "")
            if goal_type in priorities:
                goal["priority"] = round(self.memory._clamp(priorities[goal_type], default=float(goal.get("priority", 0.5) or 0.5)), 4)
            if goal_type == "identity_maintenance":
                goal["stalled_reason"] = "" if "stiffness_drift" not in deficits else "stiffness_drift"
            if goal_type == "relationship_continuity":
                goal["stalled_reason"] = "" if MindGraph.metric_value(expectations.get("reply_likelihood", 0.0), default=0.0) >= 0.2 else "low_reply_likelihood"
            if goal_type == "contact_maintenance":
                goal["stalled_reason"] = "" if MindGraph.metric_value(expectations.get("initiative_receptivity", 0.0), default=0.0) >= 0.18 else "initiative_window_cold"
            if goal_type == "cost_discipline":
                goal["stalled_reason"] = "" if budget_pressure < 0.3 else "budget_pressure"
            if goal_type == "routing_resilience":
                goal["stalled_reason"] = "" if bool(provider_state.get("fallback_ready", False)) and not list(routing_state.get("routing_gaps", [])) else "provider_fallback_unready"
            if goal_type == "cache_warmth":
                goal["stalled_reason"] = "" if float(cache_state.get("hit_ratio", 0.0) or 0.0) >= 0.22 else "cache_reuse_weak"
            if goal_type == "expression_calibration":
                goal["stalled_reason"] = "" if "expression_calibration_gap" not in engineering_deficits else "expression_calibration_gap"
            goal["last_moved_at"] = utc_now()
            goal_id = str(goal.get("goal_id", "") or "")
            if goal_id:
                goal_progress[goal_id] = MindGraph.metric_state(
                    goal.get("progress", goal_progress.get(goal_id, 0.0)),
                    default=MindGraph.metric_value(goal_progress.get(goal_id, 0.0), default=0.0),
                    confidence=0.64,
                    evidence_refs=[f"daemon:goal_arbitration:{goal_id}"],
                    updated_at=utc_now(),
                    updated_by="daemon.goal_arbitration",
                    decay_policy="goal_continuity",
                )
                pursuit_bias[goal_id] = round(float(goal.get("priority", pursuit_bias.get(goal_id, 0.0)) or 0.0), 4)
                abandonment_cost[goal_id] = round(
                    float(abandonment_cost.get(goal_id, float(goal.get("priority", 0.0) or 0.0) * 0.6) or 0.0),
                    4,
                )
            refreshed.append(goal)
        seen_goal_windows = {str(item.get("goal_id", "") or "").strip() for item in next_goal_windows if isinstance(item, dict)}
        for goal in refreshed[:10]:
            goal_id = str(goal.get("goal_id", "") or "").strip()
            if not goal_id or goal_id in seen_goal_windows:
                continue
            next_goal_windows.append(
                {
                    "goal_id": goal_id,
                    "target_thread": str(goal.get("target_thread", "") or ""),
                    "window": "next_relevant_turn" if str(goal.get("target_thread", "") or "") else "next_internal_cycle",
                }
            )
        update = self.memory.graph.update_goal_state(
            {
                "active_goals": refreshed,
                "goal_commitments": goal_commitments,
                "goal_progress": goal_progress,
                "pursuit_bias": pursuit_bias,
                "abandonment_cost": abandonment_cost,
                "goal_conflicts": [
                    {
                        "summary": "keep continuity alive without sliding back into stiffness",
                        "goal_types": ["relationship_continuity", "liveliness_balance"],
                    },
                    {
                        "summary": "keep relationship continuity warm without letting background repair crowd out the reply path",
                        "goal_types": ["relationship_continuity", "cost_discipline", "expression_calibration"],
                    },
                ],
                "next_goal_windows": next_goal_windows[:10]
                + [
                    {
                        "goal_id": "relationship_continuity:Nemoqi",
                        "goal_type": "relationship_continuity",
                        "target_thread": "Nemoqi",
                        "window": "next_relevant_turn",
                        "window_reason": "reply likelihood and initiative receptivity are both warm enough to keep the thread alive",
                    }
                ],
                "metadata": {"last_arbitrated_at": utc_now(), "source": "daemon"},
            },
            reason="daemon:goal_arbitration",
            source="daemon",
        )
        return {
            "status": "ok",
            "active_goals": list(update.get("active_goals", []))[:4],
            "goal_conflicts": list(update.get("goal_conflicts", []))[:3],
        }

    def _run_continuity_audit(self) -> dict[str, Any]:
        autobio = self.memory.graph.autobiographical_state()
        goals = self.memory.graph.goal_state()
        subject = self.memory.graph.subject_state(thread_key="Nemoqi", chat_name="Nemoqi", channel="wechat")
        metadata = dict(subject.get("metadata", {}))
        last_action = dict(metadata.get("last_selected_action", {}))
        last_action_type = str(last_action.get("action_type", "") or "")
        chapter = str(autobio.get("current_chapter", "") or "")
        active_goals = [dict(item) for item in goals.get("active_goals", []) if isinstance(item, dict)]
        relevant_goal = next((goal for goal in active_goals if str(goal.get("goal_type", "")) in {"identity_maintenance", "relationship_continuity"}), {})
        identity_consistency = 0.76 if chapter else 0.62
        if last_action_type in {"push_back", "continuity_defense"}:
            identity_consistency += 0.05
        goal_alignment = 0.72 if relevant_goal else 0.58
        payload = {
            "last_action_type": last_action_type,
            "identity_consistency": round(self.memory._clamp(identity_consistency), 4),
            "goal_alignment": round(self.memory._clamp(goal_alignment), 4),
            "current_chapter": chapter,
            "goal_type": str(relevant_goal.get("goal_type", "") or ""),
        }
        self.memory.graph.update_subject_state(
            channel="wechat",
            thread_key="Nemoqi",
            chat_name="Nemoqi",
            metadata={"continuity_audit": payload},
            note="continuity_audit",
            source="daemon",
        )
        return {"status": "ok", **payload}

    def _run_operator_planning_cycle(self) -> dict[str, Any]:
        pending = self.memory.graph.pending_operator_run()
        if pending:
            return {"status": "blocked", "blocked_reason": "pending_operator_run_exists", "pending": pending}
        return plan_operator_cycle(
            config=self.config,
            runner=self.runner,
            memory=self.memory,
            store=self.store,
            reason="daemon:operator_planning",
        )

    def _run_operator_shadow_cycle(self) -> dict[str, Any]:
        pending = self.memory.graph.pending_operator_run()
        if not pending:
            return {"status": "blocked", "blocked_reason": "no_pending_operator_run"}
        return run_operator_cycle(
            config=self.config,
            runner=self.runner,
            memory=self.memory,
            store=self.store,
            reason="daemon:operator_shadow_cycle",
        )

    def _run_visual_ingest_cycle(self) -> dict[str, Any]:
        return self.memory.drain_visual_ingest_queue(limit=max(1, int(self.config.memory.visual_sync_max_count or 1)))

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
            mode=self.brain_mode(),
        )

    def operator_probe(self, *, thread_key: str, chat_name: str, channel: str = "wechat") -> dict[str, Any]:
        return run_operator_probe(
            config=self.config,
            runner=self.runner,
            memory=self.memory,
            store=self.store,
            thread_key=thread_key,
            chat_name=chat_name,
            channel=channel,
        )

    def initiative_status(
        self,
        *,
        thread_key: str,
        chat_name: str,
        channel: str = "wechat",
        limit: int = 5,
    ) -> dict[str, Any]:
        mode = self.brain_mode()
        probe = self.initiative_probe(
            thread_key=thread_key,
            chat_name=chat_name,
            channel=channel,
            query="initiative_status",
        )
        thread = self.store.find_thread(channel=channel, thread_key=thread_key) if thread_key else None
        contact = None
        if thread:
            contact = self.store._fetchone("SELECT * FROM contacts WHERE id = ?", (int(thread["contact_id"]),))
        helper = self._wechat_settings() if channel == "wechat" else {}
        send_queue_dir = helper.get("send_queue_dir")
        sent_dir = helper.get("sent_dir")
        failed_dir = helper.get("failed_dir")
        candidates = [
            row
            for row in self.memory.list_initiative_candidates(limit=max(limit * 3, 12))
            if str(row.get("channel", "")).strip().lower() == channel
            and str(row.get("thread_key", "")).strip() == thread_key
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
            "thread_key": thread_key,
            "chat_name": chat_name,
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
            "candidates": candidates,
            "pending_jobs": pending_jobs,
        }

    def dispatch_initiatives(self, *, process_jobs: bool = True, limit: int | None = None) -> dict[str, Any]:
        social = self._run_social_cycle()
        processed: list[str] = []
        if process_jobs:
            processed = self._process_jobs(limit or self.config.runtime.max_jobs_per_cycle)
        return {
            "mode": self.brain_mode(),
            "social_stream": social,
            "processed_jobs": processed,
        }

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
