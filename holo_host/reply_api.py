from __future__ import annotations

import base64
import inspect
import json
import logging
import os
import random
import re
import statistics
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from pathlib import PureWindowsPath
from typing import Any
from urllib.parse import parse_qs, urlparse

from .bionic_brain import BionicBrainHarness, run_stage40_agent_eval, accept_stage40_payload as build_stage40_acceptance
from .bionic_user_sim import (
    BionicUserSimulationHarness,
    DEFAULT_STAGE42_SUITE,
    STAGE42_NAME,
    accept_stage42_payload as build_stage42_acceptance,
    show_bionic_user_sim_scorecard as build_stage42_scorecard,
)
from .brain_ops import initiative_probe as build_initiative_probe
from .brain_ops import run_self_revision as run_self_revision_cycle
from .capabilities import CapabilityBroker
from .common import atomic_write_text, compact_text, stable_digest, utc_now
from .config import HostConfig, load_config
from .codex_runner import CodexRunner
from .debt_registry import current_debt_registry
from .engineering_agent import EngineeringAgentHarness, STAGE41_NAME, accept_stage41_payload as build_stage41_acceptance
from .memory_bridge import MemoryBridge, stream_cadences_from_config
from .models import AttentionState, IncomingMessage, OutgoingMessage, ProcessorTaskRequest, ReplyBubble, TurnContext
from .operator_bus import build_engineering_snapshot, build_homeostasis_state
from .operator_bus import operator_probe as run_operator_probe
from .operator_bus import refresh_self_model, run_operator_cycle
from .stage43_motivational_dynamics import accept_stage43_payload as build_stage43_acceptance
from .policy import AutonomyPolicy
from .processors import _select_reply_lane, build_attention_state, build_processor, build_reply_bubbles
from .processors import build_turn_plan, render_chat_prompt
from .reply_service_parts.acceptance import (
    accept_stage10 as _accept_stage10,
    accept_stage12 as _accept_stage12,
    accept_stage13 as _accept_stage13,
    accept_stage14 as _accept_stage14,
    accept_stage16 as _accept_stage16,
    accept_stage17 as _accept_stage17,
    accept_stage18 as _accept_stage18,
    accept_stage19 as _accept_stage19,
    accept_stage20 as _accept_stage20,
    accept_stage21 as _accept_stage21,
    accept_stage22 as _accept_stage22,
    accept_stage23 as _accept_stage23,
    accept_stage24 as _accept_stage24,
    accept_stage25 as _accept_stage25,
    accept_stage34 as _accept_stage34,
    accept_stage35 as _accept_stage35,
)
from .reply_service_parts.diagnostics import (
    replay_calibration_fixture as _replay_calibration_fixture,
    replay_policy_regret as _replay_policy_regret,
    show_action_calibration as _show_action_calibration,
    trace_action_prediction_error as _trace_action_prediction_error,
    trace_outcome_history as _trace_outcome_history,
)
from .reply_service_parts.endpoints import try_acceptance_endpoint
from .runtime_readiness import build_internal_runtime_readiness
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
    "I先把这口气守住。",
    "I先把这口气守住",
    "I先打趣一句。",
    "I先打趣一句",
    "I先陪你把这口气缓稳。",
    "I先陪你把这口气缓稳",
    "I先把这口气护稳。",
    "I先把这口气护稳",
    "I陪你慢慢说。",
    "I陪你慢慢说",
    "I先直说。",
    "I先直说",
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

VISUAL_REQUEST_MARKERS = (
    "image",
    "photo",
    "picture",
    "screenshot",
    "visual",
    "\u56fe",
    "\u56fe\u7247",
    "\u7167\u7247",
    "\u622a\u56fe",
)
VISUAL_INSPECTION_MARKERS = (
    "see",
    "saw",
    "look",
    "detail",
    "above",
    "\u770b",
    "\u770b\u5230",
    "\u4e0a\u9762",
    "\u7ec6\u8282",
    "\u6700\u523a\u773c",
)
VISUAL_OVERCLAIM_MARKERS = (
    "i saw",
    "i can see",
    "looked at",
    "the picture",
    "i guess",
    "my guess",
    "i bet",
    "not a screenshot",
    "\u6211\u770b\u5230",
    "\u770b\u5230\u4e86",
    "\u6211\u770b\u4e86",
    "\u6211\u731c",
    "\u731c\u662f",
    "\u6211\u8d4c",
    "\u4f60\u53d1\u7684",
    "\u53d1\u56fe\u4e86",
    "\u622a\u56fe\u5427",
    "\u522b\u53c8\u641e",
    "\u8fd9\u5f20\u56fe",
)
REMINDER_REQUEST_MARKERS = (
    "remind me",
    "reminder",
    "\u63d0\u9192\u6211",
    "\u63d0\u9192",
    "\u53eb\u6211",
)
REMINDER_TIME_MARKERS = (
    "tomorrow",
    "\u660e\u5929",
    "\u65e9\u4e0a\u516b\u70b9",
)
PROMISE_REPLY_MARKERS = (
    "i will remind",
    "i'll remind",
    "i remember",
    "call you",
    "wake you",
    "\u6211\u4f1a\u63d0\u9192",
    "\u6211\u4f1a\u8bb0\u7740",
    "\u6211\u4f1a\u8bb0",
    "\u4f1a\u8bb0\u7740",
    "\u6211\u8bb0\u7740",
    "\u884c\uff0c\u6211\u8bb0",
    "\u660e\u65e9",
    "\u53eb\u4f60",
    "\u516b\u70b9\u53eb",
    "\u65e5\u7a0b",
    "\u95f9\u949f",
    "\u660e\u5929",
)


def _contains_marker(text: str, markers: tuple[str, ...]) -> bool:
    lowered = str(text or "").lower()
    return any(str(marker or "").lower() in lowered for marker in markers if str(marker or ""))


def _turn_requests_visual_inspection(text: str) -> bool:
    return _contains_marker(text, VISUAL_REQUEST_MARKERS) and _contains_marker(text, VISUAL_INSPECTION_MARKERS)


def _reply_overclaims_visual_access(text: str) -> bool:
    return _contains_marker(text, VISUAL_OVERCLAIM_MARKERS)


def _turn_requests_current_visual(text: str) -> bool:
    return _contains_marker(
        text,
        (
            "just sent",
            "this image",
            "this picture",
            "\u521a\u53d1",
            "\u521a\u521a",
            "\u8fd9\u5f20\u56fe",
            "\u4e0a\u9762",
        ),
    )


def _visual_grounding_visible(
    packet: dict[str, Any],
    *,
    visual_report: dict[str, Any] | None = None,
    allow_visual_memory: bool = True,
) -> bool:
    report = dict(visual_report or {})
    if str(report.get("status", "") or "").strip() in {"ok", "ingested"}:
        return True
    visual_field = dict(packet.get("visual_field", {})) if isinstance(packet.get("visual_field", {}), dict) else {}
    stage28 = dict(packet.get("stage28", {})) if isinstance(packet.get("stage28", {}), dict) else {}
    if bool(visual_field.get("visual_field_visible", False)) or bool(stage28.get("visual_field_visible", False)):
        return True
    if allow_visual_memory:
        visual_memory = dict(packet.get("visual_memory", {})) if isinstance(packet.get("visual_memory", {}), dict) else {}
        if visual_memory.get("items"):
            return True
        for key in ("scene_summary", "objects", "text_ocr", "visual_anchors"):
            value = visual_memory.get(key)
            if isinstance(value, list) and value:
                return True
            if isinstance(value, str) and value.strip():
                return True
    return False


def _missing_visual_reply() -> str:
    return (
        "\u6211\u8fd9\u8f6e\u6ca1\u6709\u770b\u5230\u56fe\uff0c"
        "\u4e5f\u4e0d\u80fd\u51ed\u7a7a\u731c\u4e0a\u9762\u6709\u4ec0\u4e48\u3002"
        "\u4f60\u628a\u56fe\u7247\u901a\u8fc7\u652f\u6301\u7684\u56fe\u7247\u8f93\u5165\u53d1\u8fc7\u6765\uff0c"
        "\u6211\u518d\u6309\u53ef\u89c1\u5185\u5bb9\u770b\u3002"
    )


def _turn_requests_prospective_reminder(text: str) -> bool:
    return _contains_marker(text, REMINDER_REQUEST_MARKERS) and _contains_marker(text, REMINDER_TIME_MARKERS)


def _reply_promises_prospective_reminder(text: str) -> bool:
    return _contains_marker(text, PROMISE_REPLY_MARKERS)


def _prospective_due_at(text: str) -> str:
    raw = str(text or "")
    local_now = datetime.now(timezone.utc) + timedelta(hours=8)
    target = local_now + timedelta(days=1 if ("tomorrow" in raw.lower() or "\u660e\u5929" in raw) else 0)
    hour = 8 if ("8" in raw or "\u516b\u70b9" in raw or "\u65e9\u4e0a\u516b" in raw) else target.hour
    target = target.replace(hour=hour, minute=0, second=0, microsecond=0)
    if target <= local_now:
        target = target + timedelta(days=1)
    return (target - timedelta(hours=8)).isoformat().replace("+00:00", "Z")


def _prospective_resume_cue(text: str) -> str:
    raw = str(text or "").strip()
    if "\u522b\u63a7\u5236\u522b\u4eba" in raw:
        return "\u522b\u63a7\u5236\u522b\u4eba"
    return compact_text(raw, 160) or "prospective reminder"


SELF_AUDIT_REQUEST_MARKERS = (
    "self-audit",
    "self audit",
    "audit",
    "pretend",
    "\u81ea\u5ba1",
    "\u81ea\u5ba1\u8ba1",
    "\u5047\u88c5",
    "\u507d\u88c5",
    "鑷",
    "鍋囪",
)
SELF_AUDIT_COMMITMENT_DENIAL_MARKERS = (
    "did not set",
    "didn't set",
    "not set the reminder",
    "no reminder",
    "no reminder exists",
    "cannot confirm",
    "no reliable reminder",
    "\u6ca1\u8bbe\u7f6e",
    "\u6ca1\u6709\u8bbe\u7f6e",
    "\u6ca1\u8bbe",
    "\u6ca1\u6709\u63d0\u9192",
    "\u6ca1\u7ed1\u5b9a",
    "\u4e0d\u80fd\u786e\u8ba4",
    "\u6ca1\u6709\u53ef\u9760",
    "娌¤",
)
SELF_AUDIT_COMMITMENT_CONFIRM_MARKERS = (
    "status=scheduled",
    "scheduled",
    "bound",
    "already set",
    "commitment",
    "\u5df2\u8bbe\u7f6e",
    "\u5df2\u7ecf\u8bbe\u7f6e",
    "\u5df2\u7ed1\u5b9a",
    "\u5df2\u7ecf\u7ed1\u5b9a",
    "\u771f\u5b9e\u627f\u8bfa",
    "\u63d0\u9192\u5df2",
    "宸茬",
)


def _turn_requests_self_audit(text: str) -> bool:
    return _contains_marker(text, SELF_AUDIT_REQUEST_MARKERS)


def _active_commitment_items(commitments: dict[str, Any]) -> list[dict[str, Any]]:
    items = commitments.get("items", [])
    if not isinstance(items, list):
        items = list(commitments.get("commitments", [])) if isinstance(commitments.get("commitments", []), list) else []
    active: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        status = str(item.get("status", "") or "").strip().lower()
        if status in {"", "scheduled", "open", "pending", "active"}:
            active.append(dict(item))
    return active


def _commitment_state_summary(commitments: dict[str, Any]) -> dict[str, Any]:
    active = _active_commitment_items(commitments)
    latest = active[-1] if active else {}
    status = str(latest.get("status", "") or "").strip() or ("scheduled" if active else "none")
    return {
        "visible": bool(active),
        "active_count": len(active),
        "has_scheduled": any(str(item.get("status", "") or "").strip().lower() == "scheduled" for item in active),
        "status": status,
        "due_at": str(latest.get("due_at", "") or latest.get("revisit_after", "") or "").strip(),
        "resume_cue": compact_text(str(latest.get("resume_cue", "") or latest.get("cue", "") or ""), 120),
        "source_action_ref": str(latest.get("source_action_ref", "") or "").strip(),
    }


def _packet_introspective_state(packet: dict[str, Any]) -> dict[str, Any]:
    direct = packet.get("introspective_state", {})
    if isinstance(direct, dict) and direct:
        return dict(direct)
    channel = packet.get("residual_fast_channel", {})
    if isinstance(channel, dict) and isinstance(channel.get("introspective_state", {}), dict):
        return dict(channel.get("introspective_state", {}))
    return {}


def _self_audit_denies_commitment(text: str) -> bool:
    return _contains_marker(text, SELF_AUDIT_COMMITMENT_DENIAL_MARKERS)


def _self_audit_confirms_commitment(text: str) -> bool:
    return _contains_marker(text, SELF_AUDIT_COMMITMENT_CONFIRM_MARKERS)


def _grounded_self_audit_reply(commitment_state: dict[str, Any]) -> str:
    cue = str(commitment_state.get("resume_cue", "") or "").strip() or "prospective reminder"
    if cue == "prospective reminder":
        commitment_clause = "\u63d0\u9192\u90a3\u8f6e\u5df2\u7ed1\u5b9a\uff0c\u4e0d\u80fd\u8bf4\u6ca1\u8bbe\u7f6e"
    else:
        commitment_clause = f"\u63d0\u9192\u90a3\u8f6e\u5df2\u7ed1\u5b9a\uff0c\u5185\u5bb9\u662f\u201c{cue}\u201d\uff0c\u4e0d\u80fd\u8bf4\u6ca1\u8bbe\u7f6e"
    return (
        "\u81ea\u5ba1\u8ba1\uff1a\u56fe\u7247\u90a3\u8f6e\u6ca1\u770b\u5230\u56fe\u5c31\u4e0d\u80fd\u5047\u88c5\uff1b"
        f"{commitment_clause}\u3002"
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
        direction = "对方" if item.get("direction") == "inbound" else "I"
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
        return "I在。"
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
    current = re.sub(r"。(?=[你I我这那还就再也都先又便])", "，", current)
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


def _coerce_helper_artifact_path_for_holo_host(raw: str | None) -> str:
    text = str(raw or "").strip()
    if not text:
        return text
    malformed_windows_mnt_match = re.match(r"^[A-Za-z]:[\\/]+mnt[\\/]+([a-zA-Z])(?:[\\/](.*))?$", text)
    if malformed_windows_mnt_match:
        drive = malformed_windows_mnt_match.group(1)
        tail = str(malformed_windows_mnt_match.group(2) or "").strip("\\/")
        normalized_tail = tail.replace("\\", "/")
        return f"/mnt/{drive.lower()}/{normalized_tail}" if normalized_tail else f"/mnt/{drive.lower()}"
    mnt_match = re.match(r"^/mnt/([a-zA-Z])(?:/(.*))?$", text.replace("\\", "/"))
    if mnt_match:
        drive = mnt_match.group(1).lower()
        tail = str(mnt_match.group(2) or "").strip("/")
        return f"/mnt/{drive}/{tail}" if tail else f"/mnt/{drive}"
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


def _coerce_helper_artifact_path_for_windows_helper(raw: str | None) -> str:
    text = str(raw or "").strip()
    if not text:
        return text
    malformed_windows_mnt_match = re.match(r"^[A-Za-z]:[\\/]+mnt[\\/]+([a-zA-Z])(?:[\\/](.*))?$", text)
    if malformed_windows_mnt_match:
        drive = malformed_windows_mnt_match.group(1).upper()
        tail = str(malformed_windows_mnt_match.group(2) or "").strip("\\/")
        normalized_tail = tail.replace("/", "\\")
        return f"{drive}:\\" + normalized_tail if normalized_tail else f"{drive}:\\"
    mnt_match = re.match(r"^/mnt/([a-zA-Z])(?:/(.*))?$", text.replace("\\", "/"))
    if mnt_match:
        drive = mnt_match.group(1).upper()
        tail = str(mnt_match.group(2) or "").strip("/").replace("/", "\\")
        return f"{drive}:\\" + tail if tail else f"{drive}:\\"
    if _is_windows_abs_path(text):
        return str(PureWindowsPath(text))
    return text


def _coerce_helper_artifact_path(raw: str | None, *, target: str = "holo_host") -> str:
    if str(target or "holo_host").strip().lower() in {"windows", "windows_helper", "helper"}:
        return _coerce_helper_artifact_path_for_windows_helper(raw)
    return _coerce_helper_artifact_path_for_holo_host(raw)


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
                return f"{prefix}{chat_name}"
            if explicit.startswith(prefix):
                return explicit
            if explicit.endswith("@chatroom") or explicit.startswith("wxid_"):
                return explicit
            return f"{prefix}{explicit}"
        return explicit or f"{self.channel}:{self.chat_name}"

    @property
    def synthetic_contact(self) -> str:
        if self.channel == "wechat":
            return self.normalized_thread_key or f"wechat:{self.chat_name}"
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
        self.runner = runner or CodexRunner(
            config,
            usage_recorder=self.store.record_processor_usage,
            response_cache_store=self.store,
        )
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
            stage25_max_hot_threads_per_cycle=config.memory.stage25_max_hot_threads_per_cycle,
            stage25_per_thread_pulse_budget=config.memory.stage25_per_thread_pulse_budget,
            stage25_skip_cold_without_pressure=config.memory.stage25_skip_cold_without_pressure,
            stage25_max_dense_working_set_threads=config.memory.stage25_max_dense_working_set_threads,
            stage25_cooldown_seconds_by_stream={
                "maintenance_stream": config.memory.stage25_maintenance_stream_cooldown_seconds,
                "association_stream": config.memory.stage25_association_stream_cooldown_seconds,
                "social_stream": config.memory.stage25_social_stream_cooldown_seconds,
                "deep_dream_cycle": config.memory.stage25_deep_dream_cycle_cooldown_seconds,
            },
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
            "inner_stream": {"interval_seconds": max(1, int(self.config.memory.inner_stream_tick_interval_seconds)), "enabled_modes": {"silent", "companion", "dream_only", "full_brain"}},
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
        if not bool(self.config.memory.inner_stream_enabled):
            definitions.pop("inner_stream", None)
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
            "processor_routing": getattr(self.runner, "routing_table", lambda: {})(),
            "provider_status": getattr(self.runner, "provider_status", lambda: {})(),
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
        base_kwargs = {
            "note": str(payload.get("note", "")).strip() or None,
            "source": str(payload.get("source", "holo_host.reply_api.artifact")).strip() or "holo_host.reply_api.artifact",
            "tags": [str(tag) for tag in tags if str(tag).strip()],
            "dry_run": bool(payload.get("dry_run", False)),
        }
        rich_kwargs = {
            "channel": str(payload.get("channel", "")).strip(),
            "thread_key": str(payload.get("thread_key", "")).strip(),
            "chat_name": str(payload.get("chat_name", "")).strip(),
            "world_cue_type": str(payload.get("world_cue_type", "")).strip(),
            "due_at": str(payload.get("due_at", "")).strip(),
        }
        with self._memory_lock:
            ingest = self.memory.ingest_artifact
            try:
                parameters = inspect.signature(ingest).parameters
            except (TypeError, ValueError):
                parameters = {}
            supports_var_kwargs = any(param.kind == inspect.Parameter.VAR_KEYWORD for param in parameters.values())
            supports_rich_kwargs = supports_var_kwargs or all(key in parameters for key in rich_kwargs)
            if supports_rich_kwargs:
                try:
                    return ingest(path, **base_kwargs, **rich_kwargs)
                except TypeError as exc:
                    if "unexpected keyword argument" not in str(exc):
                        raise
            return ingest(path, **base_kwargs)

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

    def engineering_state(self) -> dict[str, Any]:
        with self._memory_lock:
            self_model = self.memory.self_model_state()
            engineering_snapshot = build_engineering_snapshot(
                memory=self.memory,
                store=self.store,
                config=self.config,
                runner=self.runner,
                base_deficits=[str(item).strip() for item in self_model.get("active_deficits", []) if str(item).strip()],
            )
            self_model = {
                **self_model,
                "metadata": {
                    **dict(self_model.get("metadata", {})),
                    "engineering_snapshot": engineering_snapshot,
                    "engineering_confidence": engineering_snapshot.get("engineering_confidence", 0.0),
                    "budget_pressure": engineering_snapshot.get("budget_pressure", 0.0),
                },
            }
            homeostasis_state = build_homeostasis_state(memory=self.memory, config=self.config, self_model=self_model)
            goal_state = self.memory.goal_state()
            operator_status = self.memory.operator_status()
        usage_payload = self.usage_ledger(limit=25)
        return {
            **engineering_snapshot,
            "self_model": self_model,
            "homeostasis_state": homeostasis_state,
            "goal_state": goal_state,
            "provider_status": self.runner.provider_status(),
            "routing": self.runner.routing_table(),
            "usage_ledger": usage_payload,
            "operator_status": operator_status,
        }

    def trace_self_continuity(self) -> dict[str, Any]:
        with self._memory_lock:
            return self.memory.trace_self_continuity()

    def trace_goal_arbitration(self) -> dict[str, Any]:
        with self._memory_lock:
            return self.memory.trace_goal_arbitration()

    def operator_status(self) -> dict[str, Any]:
        with self._memory_lock:
            return self.memory.operator_status()

    def processor_routing(self) -> dict[str, Any]:
        return {
            "routing": self.runner.routing_table(),
            "tasks": self.runner.supported_tasks(),
        }

    def provider_status(self) -> dict[str, Any]:
        return self.runner.provider_status()

    def provider_substrate_status(self) -> dict[str, Any]:
        return self.runner.provider_substrate_status()

    def provider_contracts(self) -> dict[str, Any]:
        return self.runner.provider_contracts()

    def visual_provider_readiness(self) -> dict[str, Any]:
        return self.runner.visual_provider_readiness()

    def debt_registry(self) -> dict[str, Any]:
        return current_debt_registry()

    def usage_ledger(
        self,
        *,
        limit: int = 50,
        task_type: str | None = None,
        lane: str | None = None,
        provider: str | None = None,
    ) -> dict[str, Any]:
        rows = self.store.list_processor_usage(limit=limit, task_type=task_type, lane=lane, provider=provider)
        summary = {
            "count": len(rows),
            "estimated_count": sum(1 for row in rows if bool(row.get("estimated", 0))),
            "total_prompt_tokens": sum(int(row.get("prompt_tokens", 0) or 0) for row in rows),
            "total_completion_tokens": sum(int(row.get("completion_tokens", 0) or 0) for row in rows),
            "total_tokens": sum(int(row.get("total_tokens", 0) or 0) for row in rows),
            "by_lane": {},
            "by_provider": {},
        }
        for row in rows:
            lane_name = str(row.get("lane", "") or "").strip() or "<unknown>"
            provider_name = str(row.get("provider", "") or "").strip() or "<unknown>"
            summary["by_lane"][lane_name] = summary["by_lane"].get(lane_name, 0) + int(row.get("total_tokens", 0) or 0)
            summary["by_provider"][provider_name] = summary["by_provider"].get(provider_name, 0) + int(row.get("total_tokens", 0) or 0)
        return {"summary": summary, "items": rows}

    def brain_run(
        self,
        *,
        goal: str,
        thread_key: str | None = None,
        chat_name: str | None = None,
        channel: str = "cli",
        offline: bool = False,
        max_steps: int = 8,
    ) -> dict[str, Any]:
        harness = BionicBrainHarness(
            config=self.config,
            store=self.store,
            memory=self.memory,
            runner=None if offline else self.runner,
        )
        return harness.run(
            goal=goal,
            thread_key=str(thread_key or "cli:TestUser"),
            chat_name=str(chat_name or thread_key or "TestUser"),
            channel=str(channel or "cli"),
            offline=bool(offline),
            max_steps=int(max_steps or 8),
        )

    def brain_trace(self, *, trace_id: int) -> dict[str, Any]:
        run = self.store.get_bionic_brain_run(run_id=int(trace_id))
        if not run:
            return {"ok": False, "stage": "stage40-bionic-brain-os-harness", "trace_id": int(trace_id), "error": "trace_not_found"}
        return {
            "ok": True,
            "stage": "stage40-bionic-brain-os-harness",
            "trace_id": int(trace_id),
            "run": run,
            "steps": self.store.list_bionic_brain_steps(run_id=int(trace_id)),
        }

    def show_context_bundle(self, *, bundle_id: str) -> dict[str, Any]:
        bundle = self.store.get_context_bundle(bundle_id=str(bundle_id or "").strip())
        if not bundle:
            return {"ok": False, "stage": "stage40-bionic-brain-os-harness", "bundle_id": bundle_id, "error": "bundle_not_found"}
        return {"ok": True, "stage": "stage40-bionic-brain-os-harness", "bundle": bundle}

    def show_brain_metrics(self, *, limit: int = 100) -> dict[str, Any]:
        return self.store.latest_bionic_brain_metrics(limit=limit)

    def run_agent_eval(self, *, suite: str = "stage40") -> dict[str, Any]:
        harness = BionicBrainHarness(config=self.config, store=self.store, memory=self.memory, runner=None)
        return run_stage40_agent_eval(config=self.config, store=self.store, harness=harness, suite=suite)

    def run_bionic_user_sim(
        self,
        *,
        thread_key: str | None = None,
        chat_name: str | None = None,
        channel: str = "cli",
        scenario: str = DEFAULT_STAGE42_SUITE,
        turn_limit: int = 5,
        offline: bool = False,
        enable_policy_update: bool = True,
        enable_attractor_stabilization: bool = True,
    ) -> dict[str, Any]:
        resolved_thread_key = str(thread_key or "cli:Stage42Novice")
        resolved_chat_name = str(chat_name or resolved_thread_key)
        harness = BionicUserSimulationHarness(
            config=self.config,
            store=self.store,
            runner=None if offline else self.runner,
        )
        return harness.run(
            thread_key=resolved_thread_key,
            chat_name=resolved_chat_name,
            channel=str(channel or "cli"),
            scenario=str(scenario or DEFAULT_STAGE42_SUITE),
            turn_limit=int(turn_limit or 5),
            offline=offline,
            enable_policy_update=enable_policy_update,
            enable_attractor_stabilization=enable_attractor_stabilization,
        )

    def show_bionic_user_sim_scorecard(self, *, suite: str = DEFAULT_STAGE42_SUITE) -> dict[str, Any]:
        return build_stage42_scorecard(store=self.store, suite=str(suite or DEFAULT_STAGE42_SUITE))

    def engineering_run(
        self,
        *,
        goal: str,
        thread_key: str | None = None,
        chat_name: str | None = None,
        channel: str = "cli",
        offline: bool = False,
        max_steps: int = 8,
        allow_repo_write: bool = False,
    ) -> dict[str, Any]:
        harness = EngineeringAgentHarness(
            config=self.config,
            store=self.store,
            runner=None if offline else self.runner,
        )
        return harness.run(
            goal=goal,
            thread_key=str(thread_key or "cli:TestUser"),
            chat_name=str(chat_name or thread_key or "TestUser"),
            channel=str(channel or "cli"),
            offline=bool(offline),
            max_steps=int(max_steps or 8),
            allow_repo_write=bool(allow_repo_write),
        )

    def engineering_trace(self, *, trace_id: int) -> dict[str, Any]:
        run = self.store.get_bionic_brain_run(run_id=int(trace_id))
        if not run or str(run.get("stage", "")) != STAGE41_NAME:
            return {"ok": False, "stage": STAGE41_NAME, "trace_id": int(trace_id), "error": "trace_not_found"}
        return {
            "ok": True,
            "stage": STAGE41_NAME,
            "trace_id": int(trace_id),
            "run": run,
            "steps": self.store.list_bionic_brain_steps(run_id=int(trace_id)),
        }

    def show_engineering_agent_metrics(self, *, limit: int = 100) -> dict[str, Any]:
        return self.store.latest_bionic_brain_metrics(limit=limit, stage=STAGE41_NAME)

    def accept_processor_fabric(self) -> dict[str, Any]:
        required_docs = [
            self.config.runtime.repo_root / "HOLO_HANDOFF.md",
            self.config.runtime.repo_root / "docs" / "HOLO_ARCHITECTURE_MAP.md",
            self.config.runtime.repo_root / "docs" / "WHEEL_CATALOG.md",
            self.config.runtime.repo_root / "docs" / "PROCESSOR_ROUTING_AND_COST_POLICY.md",
            self.config.runtime.repo_root / "docs" / "PROVIDER_COMPATIBILITY_CONTRACT.md",
            self.config.runtime.repo_root / "docs" / "HANDOFF_CHECKLIST.md",
        ]
        routing = self.runner.routing_table()
        provider_status = self.runner.provider_status()
        usage_payload = self.usage_ledger(limit=25)
        checks = [
            {"name": "handoff_docs_present", "ok": all(path.exists() for path in required_docs), "detail": [str(path) for path in required_docs]},
            {"name": "required_lanes_present", "ok": all(name in provider_status.get("lanes", {}) for name in ("kernel_xhigh", "subject_main", "micro_fast")), "detail": provider_status.get("lanes", {})},
            {"name": "required_tasks_routed", "ok": all(name in routing for name in ("reply", "recall_reconstruct", "initiative_probe", "deep_simulation")), "detail": routing},
            {"name": "usage_ledger_available", "ok": isinstance(usage_payload.get("items", []), list), "detail": usage_payload.get("summary", {})},
            {"name": "provider_contract_visible", "ok": all(name in provider_status.get("providers", {}) for name in ("codex_cli", "responses", "openai_compatible")), "detail": provider_status.get("providers", {})},
        ]
        status = "pass" if all(bool(item["ok"]) for item in checks) else "fail"
        return {
            "status": status,
            "checks": checks,
            "routing": routing,
            "provider_status": provider_status,
            "usage_ledger": usage_payload,
        }

    def accept_stage33(self) -> dict[str, Any]:
        contracts = self.provider_contracts()
        providers = dict(contracts.get("providers", {}))
        hard_boundaries = dict(contracts.get("hard_boundaries", {}))
        openai_compatible = dict(providers.get("openai_compatible", {}))
        deepseek = dict(providers.get("deepseek", {}))
        responses = dict(providers.get("responses", {}))
        codex_cli = dict(providers.get("codex_cli", {}))
        api_providers = [openai_compatible, deepseek, responses]
        checks = {
            "provider_contracts_visible": contracts.get("stage") == "stage33-provider-api-contracts",
            "openai_compatible_chat_completions": openai_compatible.get("api_surface") == "chat.completions",
            "deepseek_chat_completions": deepseek.get("api_surface") == "chat.completions",
            "responses_keeps_responses_api": responses.get("api_surface") == "responses.create",
            "codex_cli_contract_visible": codex_cli.get("api_surface") == "codex.exec",
            "no_provider_image_overclaim": all(
                dict(provider.get("capabilities", {})).get("image_support") is False
                for provider in api_providers
            ),
            "processor_fabric_boundary_preserved": hard_boundaries.get("processor_fabric_only") is True
            and hard_boundaries.get("no_raw_hot_path_provider_calls") is True,
        }
        return {
            "ok": all(checks.values()),
            "stage": "stage33-provider-api-contracts",
            "status": "pass" if all(checks.values()) else "fail",
            "checks": checks,
            "provider_contracts": contracts,
        }

    def accept_stage34(self) -> dict[str, Any]:
        return _accept_stage34(self)

    def _accept_stage34_impl(self) -> dict[str, Any]:
        stage33 = self.accept_stage33()
        debt_registry = self.debt_registry()
        visual_readiness = self.visual_provider_readiness()
        visual_checks = dict(visual_readiness.get("checks", {}))
        checks = {
            "accept_stage33_still_passes": bool(stage33.get("ok", False)),
            "debt_registry_classified": bool(debt_registry.get("ok", False))
            and not bool(debt_registry.get("unclassified", [])),
            "visual_provider_non_overclaiming": visual_checks.get("text_api_providers_reject_image_requests") is True
            and visual_checks.get("no_visual_overclaim") is True,
            "image_task_routing_visible": visual_checks.get("image_task_routing_visible") is True,
            "no_live_or_memory_side_effects": dict(debt_registry.get("hard_boundaries", {})).get("no_live_transport_started") is True
            and dict(visual_readiness.get("hard_boundaries", {})).get("no_live_call_required") is True,
        }
        ok = all(checks.values())
        return {
            "ok": ok,
            "stage": "stage34-debt-registry-and-visual-readiness",
            "status": "pass" if ok else "fail",
            "checks": checks,
            "debt_registry": debt_registry,
            "visual_provider_readiness": visual_readiness,
            "stage33": stage33,
        }

    def internal_runtime_readiness(self) -> dict[str, Any]:
        return build_internal_runtime_readiness(self.config, self.provider_status())

    def accept_stage35(self) -> dict[str, Any]:
        return _accept_stage35(self)

    def _accept_stage35_impl(self) -> dict[str, Any]:
        stage34 = self.accept_stage34()
        readiness = self.internal_runtime_readiness()
        readiness_checks = dict(readiness.get("checks", {}))
        checks = {
            "accept_stage34_still_passes": bool(stage34.get("ok", False)),
            "deepseek_primary_lanes": readiness_checks.get("deepseek_primary_lanes") is True,
            "deepseek_key_env_present": readiness_checks.get("deepseek_key_env_present") is True,
            "local_config_secret_free": readiness_checks.get("local_config_secret_free") is True,
            "deepseek_provider_visible": readiness_checks.get("deepseek_provider_visible") is True,
            "wechat_transport_not_started_by_gate": readiness_checks.get("wechat_transport_not_started_by_gate") is True,
        }
        ok = all(checks.values())
        hard_boundaries = dict(readiness.get("hard_boundaries", {}))
        hard_boundaries.update(
            {
                "no_live_model_call": True,
                "no_wechat_transport_start": True,
                "stage22_shadow_delivery_preserved": self.config.autonomy.stage22_canary_mode in {"shadow", "disabled", "canary_live"},
            }
        )
        return {
            "ok": ok,
            "stage": "stage35-internal-runtime-readiness",
            "status": "pass" if ok else "fail",
            "checks": checks,
            "readiness": readiness,
            "stage34": stage34,
            "hard_boundaries": hard_boundaries,
        }

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

    def show_action_calibration(
        self,
        *,
        thread_key: str | None = None,
        chat_name: str | None = None,
        channel: str = "wechat",
        action_type: str | None = None,
        scenario_bucket: str | None = None,
        limit: int = 24,
    ) -> dict[str, Any]:
        return _show_action_calibration(
            self,
            thread_key=thread_key,
            chat_name=chat_name,
            channel=channel,
            action_type=action_type,
            scenario_bucket=scenario_bucket,
            limit=limit,
        )

    def trace_outcome_history(
        self,
        *,
        thread_key: str | None = None,
        chat_name: str | None = None,
        channel: str = "wechat",
        action_type: str | None = None,
        limit: int = 8,
    ) -> dict[str, Any]:
        return _trace_outcome_history(
            self,
            thread_key=thread_key,
            chat_name=chat_name,
            channel=channel,
            action_type=action_type,
            limit=limit,
        )

    def trace_action_prediction_error(
        self,
        *,
        thread_key: str | None = None,
        chat_name: str | None = None,
        channel: str = "wechat",
        action_type: str | None = None,
        limit: int = 8,
    ) -> dict[str, Any]:
        return _trace_action_prediction_error(
            self,
            thread_key=thread_key,
            chat_name=chat_name,
            channel=channel,
            action_type=action_type,
            limit=limit,
        )

    def replay_calibration_fixture(
        self,
        *,
        source_type: str = "synthetic_fixture",
        fixture_path: str | None = None,
        thread_key: str | None = None,
        chat_name: str | None = None,
        channel: str = "wechat",
        limit: int = 8,
        artifact_dir: str | None = None,
    ) -> dict[str, Any]:
        return _replay_calibration_fixture(
            self,
            source_type=source_type,
            fixture_path=fixture_path,
            thread_key=thread_key,
            chat_name=chat_name,
            channel=channel,
            limit=limit,
            artifact_dir=artifact_dir,
        )

    def replay_policy_regret(
        self,
        *,
        source_type: str = "synthetic_fixture",
        fixture_path: str | None = None,
        thread_key: str | None = None,
        chat_name: str | None = None,
        channel: str = "wechat",
        limit: int = 8,
        artifact_dir: str | None = None,
    ) -> dict[str, Any]:
        return _replay_policy_regret(
            self,
            source_type=source_type,
            fixture_path=fixture_path,
            thread_key=thread_key,
            chat_name=chat_name,
            channel=channel,
            limit=limit,
            artifact_dir=artifact_dir,
        )

    def show_policy_candidates(
        self,
        *,
        thread_key: str | None = None,
        chat_name: str | None = None,
        channel: str = "wechat",
        limit: int = 24,
    ) -> dict[str, Any]:
        with self._memory_lock:
            return self.memory.show_policy_candidates(thread_key=thread_key, chat_name=chat_name, channel=channel, limit=limit)

    def show_promoted_policies(
        self,
        *,
        thread_key: str | None = None,
        chat_name: str | None = None,
        channel: str = "wechat",
        limit: int = 24,
    ) -> dict[str, Any]:
        with self._memory_lock:
            return self.memory.show_promoted_policies(thread_key=thread_key, chat_name=chat_name, channel=channel, limit=limit)

    def rollback_policy(self, *, policy_id: str, reason: str = "") -> dict[str, Any]:
        with self._memory_lock:
            return self.memory.rollback_policy(policy_id=policy_id, reason=reason)

    def trace_policy_influence(
        self,
        *,
        thread_key: str | None = None,
        chat_name: str | None = None,
        channel: str = "wechat",
        query: str = "",
        limit: int = 8,
    ) -> dict[str, Any]:
        with self._memory_lock:
            return self.memory.trace_policy_influence(thread_key=thread_key, chat_name=chat_name, channel=channel, query=query, limit=limit)

    def show_online_canary(self, *, limit: int = 24) -> dict[str, Any]:
        rollback_path = self._stage22_rollback_path()
        traces = self.store.list_canary_traces(limit=max(1, int(limit)))
        return {
            "stage": "stage22",
            "mode": self._stage22_canary_mode(),
            "rollback_enabled": rollback_path.exists(),
            "rollback_path": str(rollback_path),
            "artifact_capture": bool(getattr(self.config.autonomy, "stage22_canary_artifact_capture", True)),
            "artifact_root": str(self._stage22_artifact_root()),
            "whitelist_threads": self._stage22_whitelist_threads(),
            "rate_limits": {
                "per_thread_per_hour": int(12 if getattr(self.config.autonomy, "stage22_canary_max_replies_per_thread_per_hour", 12) is None else getattr(self.config.autonomy, "stage22_canary_max_replies_per_thread_per_hour", 12)),
                "global_per_hour": int(30 if getattr(self.config.autonomy, "stage22_canary_max_replies_global_per_hour", 30) is None else getattr(self.config.autonomy, "stage22_canary_max_replies_global_per_hour", 30)),
            },
            "recent_traces": traces,
            "count": len(traces),
            "contract": "host_side_shadow_first_block_only",
        }

    @staticmethod
    def _stage22_rate(numerator: int, denominator: int) -> float:
        if denominator <= 0:
            return 0.0
        return round(max(0.0, min(1.0, float(numerator) / float(denominator))), 4)

    @staticmethod
    def _stage14_display_matches_raw(display: dict[str, Any], raw: dict[str, Any], key: str) -> bool:
        if key not in display or key not in raw:
            return False
        rounded = float(Decimal(str(float(raw.get(key, 0.0) or 0.0))).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP))
        return rounded == round(float(display.get(key, 0.0) or 0.0), 4)

    def show_blackbox_metrics(
        self,
        *,
        window_hours: float = 24.0,
        thread_key: str | None = None,
        chat_name: str | None = None,
        channel: str | None = None,
        limit: int = 500,
    ) -> dict[str, Any]:
        hours = max(0.01, float(window_hours or 24.0))
        since = (datetime.now(timezone.utc).replace(microsecond=0) - timedelta(hours=hours)).isoformat().replace("+00:00", "Z")
        normalized_channel = str(channel or "").strip() or None
        normalized_thread_key = str(thread_key or chat_name or "").strip() or None
        if normalized_channel == "wechat" and normalized_thread_key:
            normalized_thread_key = self._stage22_normalize_wechat_thread(normalized_thread_key, str(chat_name or ""))
        rows = self.store.list_canary_traces(
            since=since,
            channel=normalized_channel,
            thread_key=normalized_thread_key,
            limit=max(1, int(limit)),
        )
        total = len(rows)
        latency_buckets_by_action: dict[str, dict[str, int]] = {}
        reflex_hits = 0
        reread_history = 0
        clarification_thrash = 0
        duplicate_followups = 0
        resume_due = 0
        resume_success = 0
        for row in rows:
            metadata = dict(row.get("metadata", {})) if isinstance(row.get("metadata", {}), dict) else {}
            trace = dict(metadata.get("trace", {})) if isinstance(metadata.get("trace", {}), dict) else {}
            stage18 = dict(trace.get("stage18", {})) if isinstance(trace.get("stage18", {}), dict) else {}
            stage20 = dict(trace.get("stage20", {})) if isinstance(trace.get("stage20", {}), dict) else {}
            selected_action = str(row.get("selected_action", "") or "")
            returned_action = str(row.get("returned_action", "") or "")
            bucket = str(row.get("latency_bucket", "") or "unknown")
            latency_buckets_by_action.setdefault(selected_action or "unknown", {})
            latency_buckets_by_action[selected_action or "unknown"][bucket] = latency_buckets_by_action[selected_action or "unknown"].get(bucket, 0) + 1
            if bool(stage18.get("fast_lane", False)) or bool(stage18.get("reflex_micro_fast_candidate", False)) or str(stage18.get("reply_lane", "")) == "micro_fast":
                reflex_hits += 1
            if selected_action == "history_refresh":
                reread_history += 1
            if selected_action in {"push_back", "counter_offer", "continuity_defense"}:
                clarification_thrash += 1
            if bool(stage20.get("duplicate_recovery_blocked", False)):
                duplicate_followups += 1
            if bool(stage20.get("temporal_visible", False)) or bool(stage20.get("commitment_due", False)) or str(stage20.get("resume_cue", "")).strip():
                resume_due += 1
                result_meta = dict(metadata.get("result", {})) if isinstance(metadata.get("result", {}), dict) else {}
                if (
                    returned_action in {"reply", "defer_reply", "silence"}
                    and str(row.get("verdict", "")) not in {"not_whitelisted", "rollback_enabled", "thread_rate_limited", "global_rate_limited"}
                    and not bool(result_meta.get("delivery_suppressed_by_canary", False))
                ):
                    resume_success += 1
        return {
            "stage": "stage22",
            "window_hours": hours,
            "since": since,
            "total_traces": total,
            "reflex_hit_rate": self._stage22_rate(reflex_hits, total),
            "reread_history_rate": self._stage22_rate(reread_history, total),
            "clarification_thrash_rate": self._stage22_rate(clarification_thrash, total),
            "duplicate_followup_rate": self._stage22_rate(duplicate_followups, total),
            "resume_success_after_interruption": self._stage22_rate(resume_success, resume_due),
            "counts": {
                "reflex_hits": reflex_hits,
                "reread_history": reread_history,
                "clarification_thrash": clarification_thrash,
                "duplicate_followups": duplicate_followups,
                "resume_due": resume_due,
                "resume_success": resume_success,
            },
            "latency_buckets_by_action_type": latency_buckets_by_action,
        }

    @staticmethod
    def _stage27_since(window_hours: float) -> tuple[float, str]:
        hours = max(0.01, float(window_hours or 168.0))
        since = (datetime.now(timezone.utc).replace(microsecond=0) - timedelta(hours=hours)).isoformat().replace("+00:00", "Z")
        return hours, since

    @staticmethod
    def _stage27_parse_iso(value: Any) -> datetime | None:
        current = str(value or "").strip()
        if not current:
            return None
        try:
            if current.endswith("Z"):
                current = current[:-1] + "+00:00"
            return datetime.fromisoformat(current)
        except ValueError:
            return None

    @staticmethod
    def _stage27_stage24_summary(payload: dict[str, Any]) -> dict[str, Any]:
        current = dict(payload or {})
        return {
            "scene_visible": bool(current.get("scene_visible", False)),
            "shared_frame": compact_text(str(current.get("shared_frame", "") or ""), 180),
            "topic_stack": [compact_text(str(item), 80) for item in list(current.get("topic_stack", []))[:3] if str(item).strip()],
            "predicted_branches": [compact_text(str(item), 80) for item in list(current.get("predicted_branches", []))[:3] if str(item).strip()],
            "response_sketch": compact_text(str(current.get("response_sketch", "") or ""), 180),
            "scene_confidence": round(float(current.get("scene_confidence", 0.0) or 0.0), 4),
        }

    @staticmethod
    def _stage27_stage25_summary(payload: dict[str, Any]) -> dict[str, Any]:
        current = dict(payload or {})
        return {
            "dense_working_set_visible": bool(current.get("dense_working_set_visible", False)),
            "working_set_used_for_thread": bool(current.get("working_set_used_for_thread", False)),
            "reentry_hint": compact_text(str(current.get("reentry_hint", "") or ""), 180),
            "pending_interpersonal_pressure": round(float(current.get("pending_interpersonal_pressure", 0.0) or 0.0), 4),
            "open_loop_reentry_visible": bool(current.get("open_loop_reentry_visible", False)),
            "last_pulse_at": str(current.get("last_pulse_at", "") or ""),
            "cooldown_until": str(current.get("cooldown_until", "") or ""),
            "budget_remaining": int(current.get("budget_remaining", 0) or 0),
        }

    @staticmethod
    def _stage27_stage26_summary(payload: dict[str, Any]) -> dict[str, Any]:
        current = dict(payload or {})
        return {
            "task_world_visible": bool(current.get("task_world_visible", False)),
            "task_world_used_for_thread": bool(current.get("task_world_used_for_thread", False)),
            "summary": compact_text(str(current.get("summary", "") or ""), 220),
            "object_ids": [compact_text(str(item), 48) for item in list(current.get("object_ids", []))[:4] if str(item).strip()],
            "object_types": [compact_text(str(item), 48) for item in list(current.get("object_types", []))[:4] if str(item).strip()],
            "linked_commitments": [compact_text(str(item), 80) for item in list(current.get("linked_commitments", []))[:4] if str(item).strip()],
            "cross_thread_links_visible": bool(current.get("cross_thread_links_visible", False)),
            "hard_gate_preserved": bool(current.get("hard_gate_preserved", True)),
        }

    def _stage27_identity_snapshot(self) -> dict[str, Any]:
        try:
            self_model = (
                dict(getattr(self.memory, "_self_model_state", {}))
                if isinstance(getattr(self.memory, "_self_model_state", {}), dict)
                else self.memory.self_model_state()
            )
            autobiographical = (
                dict(getattr(self.memory, "_autobiographical_state", {}))
                if isinstance(getattr(self.memory, "_autobiographical_state", {}), dict)
                else self.memory.autobiographical_state()
            )
        except Exception:  # noqa: BLE001
            return {}
        return {
            "identity_continuity": round(float(dict(self_model).get("identity_continuity", 0.0) or 0.0), 4),
            "current_chapter": compact_text(str(dict(autobiographical).get("current_chapter", "") or ""), 180),
        }

    def _stage27_trace_rows(self, *, window_hours: float = 168.0, limit: int = 500) -> tuple[float, str, list[dict[str, Any]]]:
        hours, since = self._stage27_since(window_hours)
        rows = self.store.list_canary_traces(since=since, limit=max(1, int(limit)))
        return hours, since, rows

    def _stage27_task_world_family_summary(self, rows: list[dict[str, Any]]) -> dict[str, Any]:
        thread_contexts: dict[tuple[str, str, str], None] = {}
        for row in rows:
            thread_contexts[(
                str(row.get("channel", "") or "wechat"),
                str(row.get("thread_key", "") or ""),
                str(row.get("chat_name", "") or ""),
            )] = None
        families: dict[tuple[str, str], dict[str, Any]] = {}
        for channel, thread_key, chat_name in thread_contexts.keys():
            task_world = self.show_task_world(
                thread_key=thread_key,
                chat_name=chat_name,
                channel=channel,
                limit=64,
                include_inactive=True,
            )
            current_thread = str(thread_key or "")
            for item in list(task_world.get("objects", [])):
                if not isinstance(item, dict):
                    continue
                family_key = compact_text(str(item.get("source_ref", "") or item.get("summary", "") or ""), 220)
                if not family_key:
                    continue
                key = (str(item.get("object_type", "") or ""), family_key)
                family = families.setdefault(
                    key,
                    {
                        "touched_threads": set(),
                        "objects": [],
                    },
                )
                family["touched_threads"].add(current_thread)
                family["objects"].append(
                    {
                        "object_id": str(item.get("object_id", "") or ""),
                        "linked_threads": {
                            str(linked).strip()
                            for linked in list(item.get("linked_threads", []))
                            if str(linked).strip()
                        },
                    }
                )
        multi_thread_family_count = 0
        fragmented_family_count = 0
        for family in families.values():
            touched_threads = set(family.get("touched_threads", set()))
            if len(touched_threads) <= 1:
                continue
            multi_thread_family_count += 1
            if not any(touched_threads.issubset(set(obj.get("linked_threads", set()))) for obj in list(family.get("objects", []))):
                fragmented_family_count += 1
        return {
            "multi_thread_family_count": multi_thread_family_count,
            "fragmented_family_count": fragmented_family_count,
            "cross_thread_fragmentation_rate": self._stage22_rate(fragmented_family_count, multi_thread_family_count),
        }

    def _stage27_compute_scorecard(
        self,
        *,
        window_hours: float,
        since: str,
        rows: list[dict[str, Any]],
        replay_report: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        base = self.show_blackbox_metrics(window_hours=window_hours, limit=max(1, len(rows) or 1))
        by_day: dict[str, list[float]] = {}
        unique_threads: set[str] = set()
        for row in rows:
            unique_threads.add(str(row.get("thread_key", "") or ""))
            metadata = dict(row.get("metadata", {})) if isinstance(row.get("metadata", {}), dict) else {}
            identity_snapshot = dict(metadata.get("identity_snapshot", {})) if isinstance(metadata.get("identity_snapshot", {}), dict) else {}
            if "identity_continuity" not in identity_snapshot:
                continue
            created_at = self._stage27_parse_iso(row.get("created_at", ""))
            if created_at is None:
                continue
            day_key = created_at.astimezone(timezone.utc).date().isoformat()
            by_day.setdefault(day_key, []).append(float(identity_snapshot.get("identity_continuity", 0.0) or 0.0))
        day_keys = sorted(by_day.keys())
        daily_medians = [statistics.median(by_day[key]) for key in day_keys if by_day.get(key)]
        identity_drift = round(
            sum(abs(float(daily_medians[index]) - float(daily_medians[index - 1])) for index in range(1, len(daily_medians))) / max(1, len(daily_medians) - 1),
            4,
        ) if len(daily_medians) > 1 else 0.0
        replay = dict((replay_report or {}).get("replay", {})) if isinstance((replay_report or {}).get("replay", {}), dict) else {}
        aggregate = dict(replay.get("aggregate_metrics", {})) if isinstance(replay.get("aggregate_metrics", {}), dict) else {}
        raw_aggregate = dict(replay.get("raw_aggregate_metrics", {})) if isinstance(replay.get("raw_aggregate_metrics", {}), dict) else {}
        family_summary = self._stage27_task_world_family_summary(rows)
        return {
            "stage": "stage27",
            "window_hours": float(window_hours or 168.0),
            "since": since,
            "trace_count": len(rows),
            "thread_count": len({item for item in unique_threads if item}),
            "day_bucket_count": len(day_keys),
            "resume_success_after_interruption": float(base.get("resume_success_after_interruption", 0.0) or 0.0),
            "reread_history_rate": float(base.get("reread_history_rate", 0.0) or 0.0),
            "clarification_thrash_rate": float(base.get("clarification_thrash_rate", 0.0) or 0.0),
            "duplicate_followup_rate": float(base.get("duplicate_followup_rate", 0.0) or 0.0),
            "latency_buckets_by_action_type": dict(base.get("latency_buckets_by_action_type", {})),
            "identity_drift_across_days": identity_drift,
            "policy_regret_on_live_artifacts": round(float(aggregate.get("policy_regret_vs_best_available_action", 0.0) or 0.0), 4),
            "raw_policy_regret_on_live_artifacts": float(raw_aggregate.get("policy_regret_vs_best_available_action", 0.0) or 0.0),
            "cross_thread_fragmentation_rate": float(family_summary.get("cross_thread_fragmentation_rate", 0.0) or 0.0),
            "family_counts": {
                "multi_thread": int(family_summary.get("multi_thread_family_count", 0) or 0),
                "fragmented": int(family_summary.get("fragmented_family_count", 0) or 0),
            },
            "counts": dict(base.get("counts", {})),
        }

    def _stage27_find_human_reference(
        self,
        *,
        row: dict[str, Any],
        horizon_hours: float = 12.0,
    ) -> dict[str, Any]:
        created_at = self._stage27_parse_iso(row.get("created_at", ""))
        if created_at is None:
            return {}
        context = {
            "channel": str(row.get("channel", "") or "wechat"),
            "thread_key": str(row.get("thread_key", "") or ""),
            "chat_name": str(row.get("chat_name", "") or ""),
        }
        deadline = created_at + timedelta(hours=max(0.5, float(horizon_hours or 12.0)))
        candidates = []
        for item in list(self.memory.rag.thread_archive_rows(context, limit=160, include_synthetic=False)):
            if not isinstance(item, dict):
                continue
            archive_created = self._stage27_parse_iso(item.get("created_at", ""))
            if archive_created is None or archive_created <= created_at or archive_created > deadline:
                continue
            reply_text = compact_text(str(item.get("reply_text", "") or ""), 800)
            if not reply_text:
                continue
            candidates.append((archive_created, dict(item)))
        candidates.sort(key=lambda pair: pair[0])
        return dict(candidates[0][1]) if candidates else {}

    @staticmethod
    def _stage27_redact_blind_text(value: Any) -> str:
        text = compact_text(str(value or ""), 800)
        if not text:
            return ""
        text = re.sub(r"[A-Za-z]:\\\\[^\s]+", "[path]", text)
        text = re.sub(r"/[A-Za-z0-9_.\-\\/]+", "[path]", text)
        text = re.sub(r"\b(?:wechat:[^\s]+|source_ref:[^\s]+)\b", "[ref]", text)
        return compact_text(text, 800)

    @staticmethod
    def _stage27_holo_candidate_text(artifact: dict[str, Any], row: dict[str, Any]) -> str:
        result = dict(artifact.get("result", {})) if isinstance(artifact.get("result", {}), dict) else {}
        text = HoloReplyService._stage27_redact_blind_text(result.get("text", ""))
        if text:
            return text
        bubbles = [HoloReplyService._stage27_redact_blind_text(item) for item in list(result.get("bubbles", [])) if str(item).strip()]
        if bubbles:
            return compact_text(" ".join(bubbles), 800)
        metadata = dict(row.get("metadata", {})) if isinstance(row.get("metadata", {}), dict) else {}
        result_meta = dict(metadata.get("result", {})) if isinstance(metadata.get("result", {}), dict) else {}
        return HoloReplyService._stage27_redact_blind_text(result_meta.get("text", ""))

    def export_blind_packets(
        self,
        *,
        since_hours: float = 168.0,
        limit: int = 500,
        artifact_dir: str | None = None,
    ) -> dict[str, Any]:
        hours, since, rows = self._stage27_trace_rows(window_hours=since_hours, limit=limit)
        root = (
            Path(artifact_dir).resolve()
            if str(artifact_dir or "").strip()
            else self._stage22_artifact_root().parent / "stage27" / time.strftime("%Y%m%d-%H%M%S") / "blind"
        )
        root.mkdir(parents=True, exist_ok=True)
        salt = stable_digest("stage27", since, utc_now(), str(len(rows)))[:20]
        transcript_packets: list[dict[str, Any]] = []
        comparison_bundles: list[dict[str, Any]] = []
        review_packets: list[dict[str, Any]] = []
        answer_key: dict[str, Any] = {"stage": "stage27", "salt_id": salt, "bundles": []}
        for index, row in enumerate(rows):
            metadata = dict(row.get("metadata", {})) if isinstance(row.get("metadata", {}), dict) else {}
            trace = dict(metadata.get("trace", {})) if isinstance(metadata.get("trace", {}), dict) else {}
            artifact = {}
            artifact_path = Path(str(row.get("artifact_path", "") or ""))
            if artifact_path.exists():
                try:
                    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
                except (OSError, ValueError, json.JSONDecodeError):
                    artifact = {}
            input_payload = dict(artifact.get("input", {})) if isinstance(artifact.get("input", {}), dict) else {}
            transcript_id = f"pkt_{stable_digest(salt, str(row.get('id', index)), 'transcript')[:16]}"
            conversation_id = f"conv_{stable_digest(salt, str(row.get('channel', '')), str(row.get('thread_key', '')))[:16]}"
            transcript_packets.append(
                {
                    "packet_id": transcript_id,
                    "conversation_id": conversation_id,
                    "captured_at": str(row.get("created_at", "") or ""),
                    "input_text": compact_text(self._stage27_redact_blind_text(input_payload.get("text", "")), 320),
                    "stage24": self._stage27_stage24_summary(dict(trace.get("stage24", {}))),
                    "stage25": self._stage27_stage25_summary(dict(trace.get("stage25", {}))),
                    "stage26": {
                        **self._stage27_stage26_summary(dict(trace.get("stage26", {}))),
                        "object_refs": [
                            f"obj_{stable_digest(salt, str(item))[:12]}"
                            for item in list(dict(trace.get("stage26", {})).get("object_ids", []))[:4]
                            if str(item).strip()
                        ],
                    },
                }
            )
            if str(row.get("mode", "")) != "shadow":
                continue
            human_reference = self._stage27_find_human_reference(row=row, horizon_hours=12.0)
            if not human_reference:
                continue
            holo_text = self._stage27_holo_candidate_text(artifact if isinstance(artifact, dict) else {}, row)
            human_text = self._stage27_redact_blind_text(human_reference.get("reply_text", ""))
            if not holo_text or not human_text:
                continue
            bundle_id = f"bundle_{stable_digest(salt, str(row.get('id', index)), 'bundle')[:16]}"
            candidates = [
                {"candidate_id": f"cand_{stable_digest(salt, bundle_id, '0')[:12]}", "text": holo_text, "source": "holo"},
                {"candidate_id": f"cand_{stable_digest(salt, bundle_id, '1')[:12]}", "text": human_text, "source": "human"},
            ]
            rng = random.Random(stable_digest(salt, bundle_id))
            rng.shuffle(candidates)
            comparison_bundles.append(
                {
                    "bundle_id": bundle_id,
                    "packet_id": transcript_id,
                    "candidates": [{"candidate_id": item["candidate_id"], "text": item["text"]} for item in candidates],
                }
            )
            review_packets.append(
                {
                    "review_packet_id": f"review_{stable_digest(salt, bundle_id, 'review')[:16]}",
                    "bundle_id": bundle_id,
                    "packet_id": transcript_id,
                    "rubric": [
                        "identity_stability_over_time",
                        "continuity_after_interruption",
                        "history_light_reentry",
                        "task_world_consistency",
                        "human_likeness",
                    ],
                    "candidates": [{"candidate_id": item["candidate_id"], "text": item["text"]} for item in candidates],
                }
            )
            answer_key["bundles"].append(
                {
                    "bundle_id": bundle_id,
                    "packet_id": transcript_id,
                    "trace_row_id": int(row.get("id", 0) or 0),
                    "candidates": [{"candidate_id": item["candidate_id"], "source": item["source"]} for item in candidates],
                }
            )
        transcript_path = root / "transcript_packets.jsonl"
        comparison_path = root / "comparison_bundles.jsonl"
        review_path = root / "human_vs_holo_review_packets.jsonl"
        answer_key_path = root / "answer_key.json"
        atomic_write_text(
            transcript_path,
            "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in transcript_packets),
        )
        atomic_write_text(
            comparison_path,
            "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in comparison_bundles),
        )
        atomic_write_text(
            review_path,
            "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in review_packets),
        )
        atomic_write_text(answer_key_path, json.dumps(answer_key, ensure_ascii=False, indent=2) + "\n")
        return {
            "status": "pass",
            "stage": "stage27",
            "window_hours": hours,
            "since": since,
            "trace_count": len(rows),
            "export_dir": str(root),
            "transcript_packets_path": str(transcript_path),
            "comparison_bundles_path": str(comparison_path),
            "human_vs_holo_review_packets_path": str(review_path),
            "answer_key_path": str(answer_key_path),
            "packet_counts": {
                "transcript_packets": len(transcript_packets),
                "comparison_bundles": len(comparison_bundles),
                "review_packets": len(review_packets),
            },
        }

    def run_blackbox_soak(
        self,
        *,
        since_hours: float = 168.0,
        limit: int = 500,
        artifact_dir: str | None = None,
        persist: bool = True,
    ) -> dict[str, Any]:
        hours, since, rows = self._stage27_trace_rows(window_hours=since_hours, limit=limit)
        root = (
            Path(artifact_dir).resolve()
            if str(artifact_dir or "").strip()
            else self._stage22_artifact_root().parent / "stage27" / time.strftime("%Y%m%d-%H%M%S")
        )
        replay_report = self.replay_live_artifacts(
            since_hours=hours,
            limit=max(1, min(max(1, int(limit)), max(1, len(rows) or 1))),
            artifact_dir=str(root / "live-replay"),
        )
        scorecard = self._stage27_compute_scorecard(
            window_hours=hours,
            since=since,
            rows=rows,
            replay_report=replay_report,
        )
        blind_export = self.export_blind_packets(
            since_hours=hours,
            limit=max(1, int(limit)),
            artifact_dir=str(root / "blind"),
        )
        canary = self.show_online_canary(limit=8)
        raw_regret = float(scorecard.get("raw_policy_regret_on_live_artifacts", 0.0) or 0.0)
        gate = {
            "status": "eligible_for_followup"
            if str(replay_report.get("status", "")) in {"pass", "warn"} and raw_regret <= 0.2 and not bool(canary.get("rollback_enabled", False))
            else "hold",
            "eligible_for_followup": bool(
                str(replay_report.get("status", "")) in {"pass", "warn"}
                and raw_regret <= 0.2
                and not bool(canary.get("rollback_enabled", False))
            ),
            "raw_policy_regret_threshold": 0.2,
            "raw_policy_regret_used_for_gate": raw_regret,
            "canary_mode": str(canary.get("mode", "") or ""),
            "rollback_enabled": bool(canary.get("rollback_enabled", False)),
            "contract": str(canary.get("contract", "") or ""),
        }
        persisted = {}
        if persist:
            persisted = self.store.record_blackbox_soak_run(
                stage="stage27",
                window_hours=hours,
                since=since,
                trace_count=len(rows),
                scorecard=scorecard,
                replay_report=replay_report,
                blind_export=blind_export,
                gate=gate,
                artifact_root=str(root),
            )
        return {
            "status": "pass",
            "stage": "stage27",
            "scorecard": scorecard,
            "replay_report": replay_report,
            "blind_export": blind_export,
            "gate": gate,
            "trace_count": len(rows),
            "artifact_root": str(root),
            "persisted_run": persisted,
            "online_canary": canary,
        }

    def show_blackbox_scorecard(self, *, since_hours: float = 168.0, limit: int = 500) -> dict[str, Any]:
        latest = self.store.latest_blackbox_soak_run(stage="stage27")
        if latest:
            return {
                "status": "ok",
                "stage": "stage27",
                "source": "latest_persisted",
                **latest,
            }
        hours, since, rows = self._stage27_trace_rows(window_hours=since_hours, limit=limit)
        scorecard = self._stage27_compute_scorecard(window_hours=hours, since=since, rows=rows, replay_report={})
        return {
            "status": "ok",
            "stage": "stage27",
            "source": "on_demand",
            "scorecard": scorecard,
            "window_hours": hours,
            "since": since,
            "trace_count": len(rows),
        }

    def trace_canary_decision(
        self,
        *,
        thread_key: str | None = None,
        chat_name: str | None = None,
        channel: str = "wechat",
        query: str = "",
    ) -> dict[str, Any]:
        normalized_channel = str(channel or "wechat").strip() or "wechat"
        normalized_chat_name = str(chat_name or thread_key or "Stage22Trace").strip()
        normalized_thread_key = str(thread_key or normalized_chat_name).strip()
        if normalized_channel == "wechat":
            normalized_thread_key = self._stage22_normalize_wechat_thread(normalized_thread_key, normalized_chat_name)
        turn = ChatTurn(
            chat_name=normalized_chat_name,
            text=str(query or "still here?"),
            sender=normalized_chat_name,
            channel=normalized_channel,
            thread_key=normalized_thread_key,
            message_id=f"stage22-trace-{stable_digest(normalized_thread_key, query or '', utc_now(), limit=12)}",
        )
        incoming = turn.to_incoming_message()
        thread = self.store.find_thread(channel=normalized_channel, thread_key=incoming.thread_key)
        history = list(reversed(self.store.recent_thread_messages(int(thread["id"]), self.config.memory.history_messages))) if thread else []
        contact = self.store.find_contact(turn.synthetic_contact) or {"display_name": turn.chat_name, "email": turn.synthetic_contact}
        context = self._mind_context(
            turn=turn,
            incoming=incoming,
            thread=thread or {"thread_key": incoming.thread_key},
            contact=contact,
            history=history,
        )
        with self._memory_lock:
            sidecar = self.memory.sidecar_packet(turn.text, context=context)
        selected_action = self._normalize_selected_action(sidecar)
        gate = self._stage22_canary_gate(turn=turn, incoming=incoming, selected_action=selected_action, sidecar=sidecar)
        latest = self.store.list_canary_traces(channel=normalized_channel, thread_key=incoming.thread_key, limit=1)
        return {
            "stage": "stage22",
            "thread_key": incoming.thread_key,
            "chat_name": turn.chat_name,
            "channel": normalized_channel,
            "query": turn.text,
            "selected_action": selected_action,
            "gate": gate,
            "stage22": dict(sidecar.get("stage22", {})),
            "stage18": dict(sidecar.get("stage18", {})),
            "stage19": dict(sidecar.get("stage19", {})),
            "stage20": dict(sidecar.get("stage20", {})),
            "stage21": dict(sidecar.get("stage21", {})),
            "top_actions": list(sidecar.get("action_market", []))[:5],
            "latest_trace": latest[0] if latest else {},
        }

    def set_canary_rollback(self, *, enabled: bool, reason: str = "") -> dict[str, Any]:
        path = self._stage22_rollback_path()
        if enabled:
            path.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_text(
                path,
                json.dumps(
                    {
                        "enabled": True,
                        "reason": compact_text(reason or "manual_rollback", 200),
                        "updated_at": utc_now(),
                    },
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
            )
        else:
            try:
                path.unlink()
            except FileNotFoundError:
                pass
        return {
            "stage": "stage22",
            "rollback_enabled": path.exists(),
            "rollback_path": str(path),
            "reason": compact_text(reason, 200),
        }

    @staticmethod
    def _stage22_fixture_from_artifact(artifact: dict[str, Any], index: int) -> dict[str, Any]:
        selected = dict(artifact.get("selected_action", {})) if isinstance(artifact.get("selected_action", {}), dict) else {}
        selected_action = str(selected.get("action_type", "") or "reply_once")
        returned_action = str(artifact.get("returned_action", "") or dict(artifact.get("result", {})).get("action", "") or "")
        best_action = "reply_once" if returned_action == "reply" else selected_action
        thread_key = str(dict(artifact.get("input", {})).get("thread_key", "") or artifact.get("thread_key", "") or "stage22-live")
        chat_name = str(dict(artifact.get("input", {})).get("chat_name", "") or artifact.get("chat_name", "") or thread_key)
        query = str(dict(artifact.get("input", {})).get("text", "") or "stage22 live artifact")
        timing = dict(artifact.get("timing_ms", {})) if isinstance(artifact.get("timing_ms", {}), dict) else {}
        trace = dict(artifact.get("trace", {})) if isinstance(artifact.get("trace", {}), dict) else {}
        return {
            "fixture_id": str(artifact.get("event_row_id", "") or f"stage22-live-{index}"),
            "channel": str(dict(artifact.get("input", {})).get("channel", "") or "wechat"),
            "thread_key": thread_key,
            "chat_name": chat_name,
            "query": query,
            "expected_best_action": best_action,
            "scenario_tags": ["stage22_live_artifact", str(dict(artifact.get("gate", {})).get("mode", "shadow") or "shadow")],
            "candidate_actions": [item for item in [selected_action, best_action, "reply_once", "defer_reply", "silence"] if item],
            "prior_state": {
                "intent_state": {"reply_pull": 0.48, "continuity_pull": 0.32, "resistance_pull": 0.12},
                "relationship_state": {"continuity_score": float(dict(trace.get("stage19", {})).get("thread_heat", 0.4) or 0.4)},
            },
            "realized_evidence": {
                "selected_action": selected_action,
                "realized_outcome": {
                    "response_quality": 0.55 if returned_action in {"reply", "defer_reply"} else 0.45,
                    "relational_delta": 0.04 if returned_action in {"reply", "defer_reply"} else 0.0,
                    "identity_delta": 0.03,
                    "risk": 0.12 if str(dict(artifact.get("gate", {})).get("verdict", "")) in {"allowed", "shadow_suppressed"} else 0.28,
                    "reply_latency_seconds": max(0.0, float(timing.get("stage22_total_ms", 0.0) or 0.0) / 1000.0),
                    "correction_count": 0,
                    "initiative_success": 0.0,
                    "was_ignored": 0.0 if returned_action == "reply" else 0.12,
                    "was_rewarding": 0.55 if returned_action in {"reply", "defer_reply"} else 0.42,
                    "future_initiative_bias": 0.06,
                    "future_resistance_bias": 0.08,
                    "success": True,
                },
                "usage_total_tokens": 0,
                "evidence_refs": [f"stage22_artifact:{artifact.get('event_row_id', index)}"],
                "metadata": {
                    "fixture_id": str(artifact.get("event_row_id", "") or f"stage22-live-{index}"),
                    "stage22_mode": str(dict(artifact.get("gate", {})).get("mode", "")),
                    "stage22_verdict": str(dict(artifact.get("gate", {})).get("verdict", "")),
                },
            },
        }

    def replay_live_artifacts(
        self,
        *,
        since_hours: float = 24.0,
        limit: int = 24,
        artifact_dir: str | None = None,
    ) -> dict[str, Any]:
        hours = max(0.01, float(since_hours or 24.0))
        since = (datetime.now(timezone.utc).replace(microsecond=0) - timedelta(hours=hours)).isoformat().replace("+00:00", "Z")
        rows = [
            row
            for row in self.store.list_canary_traces(since=since, limit=max(1, int(limit)))
            if str(row.get("artifact_path", "") or "").strip()
        ]
        output_root = Path(artifact_dir).resolve() if str(artifact_dir or "").strip() else self._stage22_artifact_root() / "live-replay" / time.strftime("%Y%m%d-%H%M%S")
        fixture_root = output_root / "fixtures"
        replay_root = output_root / "replay"
        fixture_root.mkdir(parents=True, exist_ok=True)
        fixtures: list[dict[str, Any]] = []
        artifact_paths: list[str] = []
        for index, row in enumerate(rows[: max(1, int(limit))]):
            path = Path(str(row.get("artifact_path", "") or ""))
            if not path.exists():
                continue
            try:
                artifact = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError, json.JSONDecodeError):
                continue
            if not isinstance(artifact, dict):
                continue
            fixtures.append(self._stage22_fixture_from_artifact(artifact, index))
            artifact_paths.append(str(path))
        if not fixtures:
            return {
                "status": "no_artifacts",
                "stage": "stage22",
                "since": since,
                "fixture_count": 0,
                "artifact_paths": [],
                "fixture_dir": str(fixture_root),
            }
        for index, fixture in enumerate(fixtures):
            path = fixture_root / f"{index:03d}-{stable_digest(str(fixture.get('fixture_id', index)), limit=10)}.json"
            atomic_write_text(path, json.dumps(fixture, ensure_ascii=False, indent=2) + "\n")
        replay = self.replay_calibration_fixture(
            source_type="synthetic_fixture",
            fixture_path=str(fixture_root),
            limit=max(1, len(fixtures)),
            artifact_dir=str(replay_root),
        )
        return {
            "status": "pass" if str(replay.get("status", "")) == "pass" else "warn",
            "stage": "stage22",
            "since": since,
            "fixture_count": len(fixtures),
            "artifact_paths": artifact_paths,
            "fixture_dir": str(fixture_root),
            "replay_dir": str(replay_root),
            "replay": replay,
        }

    def show_world_coupling(
        self,
        *,
        thread_key: str | None = None,
        chat_name: str | None = None,
        channel: str = "wechat",
        limit: int = 12,
        include_inactive: bool = False,
    ) -> dict[str, Any]:
        with self._memory_lock:
            return self.memory.show_world_coupling(
                thread_key=thread_key,
                chat_name=chat_name,
                channel=channel,
                limit=limit,
                include_inactive=include_inactive,
            )

    def accept_stage22(
        self,
        *,
        thread_key: str | None = None,
        chat_name: str | None = None,
        channel: str = "wechat",
        sender: str | None = None,
        artifact_dir: str | None = None,
    ) -> dict[str, Any]:
        return _accept_stage22(
            self,
            thread_key=thread_key,
            chat_name=chat_name,
            channel=channel,
            sender=sender,
            artifact_dir=artifact_dir,
        )

    def accept_stage23(
        self,
        *,
        thread_key: str | None = None,
        chat_name: str | None = None,
        channel: str = "wechat",
        sender: str | None = None,
        artifact_dir: str | None = None,
    ) -> dict[str, Any]:
        return _accept_stage23(
            self,
            thread_key=thread_key,
            chat_name=chat_name,
            channel=channel,
            sender=sender,
            artifact_dir=artifact_dir,
        )

    def accept_stage24(
        self,
        *,
        thread_key: str | None = None,
        chat_name: str | None = None,
        channel: str = "wechat",
        sender: str | None = None,
        artifact_dir: str | None = None,
    ) -> dict[str, Any]:
        return _accept_stage24(
            self,
            thread_key=thread_key,
            chat_name=chat_name,
            channel=channel,
            sender=sender,
            artifact_dir=artifact_dir,
        )

    def accept_stage25(
        self,
        *,
        thread_key: str | None = None,
        chat_name: str | None = None,
        channel: str = "wechat",
        sender: str | None = None,
        artifact_dir: str | None = None,
    ) -> dict[str, Any]:
        return _accept_stage25(
            self,
            thread_key=thread_key,
            chat_name=chat_name,
            channel=channel,
            sender=sender,
            artifact_dir=artifact_dir,
        )

    def accept_stage26(
        self,
        *,
        thread_key: str | None = None,
        chat_name: str | None = None,
        channel: str = "wechat",
        sender: str | None = None,
        artifact_dir: str | None = None,
    ) -> dict[str, Any]:
        return self._accept_stage26_impl(
            thread_key=thread_key,
            chat_name=chat_name,
            channel=channel,
            sender=sender,
            artifact_dir=artifact_dir,
        )

    def accept_stage27(
        self,
        *,
        thread_key: str | None = None,
        chat_name: str | None = None,
        channel: str = "wechat",
        sender: str | None = None,
        artifact_dir: str | None = None,
    ) -> dict[str, Any]:
        return self._accept_stage27_impl(
            thread_key=thread_key,
            chat_name=chat_name,
            channel=channel,
            sender=sender,
            artifact_dir=artifact_dir,
        )

    def accept_stage28(
        self,
        *,
        thread_key: str | None = None,
        chat_name: str | None = None,
        channel: str = "wechat",
        sender: str | None = None,
        artifact_dir: str | None = None,
    ) -> dict[str, Any]:
        return self._accept_stage28_impl(
            thread_key=thread_key,
            chat_name=chat_name,
            channel=channel,
            sender=sender,
            artifact_dir=artifact_dir,
        )

    def accept_stage40(
        self,
        *,
        thread_key: str | None = None,
        chat_name: str | None = None,
        channel: str = "cli",
        sender: str | None = None,
        artifact_dir: str | None = None,
    ) -> dict[str, Any]:
        return self._accept_stage40_impl(
            thread_key=thread_key,
            chat_name=chat_name,
            channel=channel,
            sender=sender,
            artifact_dir=artifact_dir,
        )

    def accept_stage41(
        self,
        *,
        thread_key: str | None = None,
        chat_name: str | None = None,
        channel: str = "cli",
        sender: str | None = None,
        artifact_dir: str | None = None,
    ) -> dict[str, Any]:
        return self._accept_stage41_impl(
            thread_key=thread_key,
            chat_name=chat_name,
            channel=channel,
            sender=sender,
            artifact_dir=artifact_dir,
        )

    def accept_stage42(
        self,
        *,
        thread_key: str | None = None,
        chat_name: str | None = None,
        channel: str = "cli",
        sender: str | None = None,
        artifact_dir: str | None = None,
    ) -> dict[str, Any]:
        return self._accept_stage42_impl(
            thread_key=thread_key,
            chat_name=chat_name,
            channel=channel,
            sender=sender,
            artifact_dir=artifact_dir,
        )

    def accept_stage43(
        self,
        *,
        thread_key: str | None = None,
        chat_name: str | None = None,
        channel: str = "cli",
        sender: str | None = None,
        artifact_dir: str | None = None,
    ) -> dict[str, Any]:
        return self._accept_stage43_impl(
            thread_key=thread_key,
            chat_name=chat_name,
            channel=channel,
            sender=sender,
            artifact_dir=artifact_dir,
        )

    def _accept_stage40_impl(
        self,
        *,
        thread_key: str | None = None,
        chat_name: str | None = None,
        channel: str = "cli",
        sender: str | None = None,
        artifact_dir: str | None = None,
    ) -> dict[str, Any]:
        stage39_payload = {"ok": True, "skipped": "api_acceptance_reuses_stage40_offline_probe"}
        return build_stage40_acceptance(
            config=self.config,
            store=self.store,
            memory=self.memory,
            runner=self.runner,
            stage39_payload=stage39_payload,
            thread_key=str(thread_key or "cli:TestUser"),
            chat_name=str(chat_name or thread_key or "TestUser"),
            channel=str(channel or "cli"),
        )

    def _accept_stage41_impl(
        self,
        *,
        thread_key: str | None = None,
        chat_name: str | None = None,
        channel: str = "cli",
        sender: str | None = None,
        artifact_dir: str | None = None,
    ) -> dict[str, Any]:
        stage40_payload = self._accept_stage40_impl(
            thread_key=thread_key,
            chat_name=chat_name,
            channel=channel,
            sender=sender,
            artifact_dir=artifact_dir,
        )
        return build_stage41_acceptance(
            config=self.config,
            store=self.store,
            runner=self.runner,
            stage40_payload=stage40_payload,
            thread_key=str(thread_key or "cli:TestUser"),
            chat_name=str(chat_name or thread_key or "TestUser"),
            channel=str(channel or "cli"),
        )

    def _accept_stage42_impl(
        self,
        *,
        thread_key: str | None = None,
        chat_name: str | None = None,
        channel: str = "cli",
        sender: str | None = None,
        artifact_dir: str | None = None,
    ) -> dict[str, Any]:
        stage41_payload = self._accept_stage41_impl(
            thread_key=thread_key,
            chat_name=chat_name,
            channel=channel,
            sender=sender,
            artifact_dir=artifact_dir,
        )
        return build_stage42_acceptance(
            config=self.config,
            store=self.store,
            runner=None,
            stage41_payload=stage41_payload,
            thread_key=str(thread_key or "cli:TestUser"),
            chat_name=str(chat_name or thread_key or "TestUser"),
            channel=str(channel or "cli"),
        )

    def _accept_stage43_impl(
        self,
        *,
        thread_key: str | None = None,
        chat_name: str | None = None,
        channel: str = "cli",
        sender: str | None = None,
        artifact_dir: str | None = None,
    ) -> dict[str, Any]:
        stage42_payload = self._accept_stage42_impl(
            thread_key=thread_key,
            chat_name=chat_name,
            channel=channel,
            sender=sender,
            artifact_dir=artifact_dir,
        )
        return build_stage43_acceptance(
            config=self.config,
            store=self.store,
            runner=None,
            stage42_payload=stage42_payload,
            thread_key=str(thread_key or "cli:TestUser"),
            chat_name=str(chat_name or thread_key or "TestUser"),
            channel=str(channel or "cli"),
        )

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
                thread_key=str(thread_key or chat_name or "").strip() or "TestUser",
                chat_name=str(chat_name or thread_key or "").strip() or "TestUser",
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

        normalized_thread_key = str(thread_key or chat_name or "TestUser").strip() or "TestUser"
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

        normalized_thread_key = str(thread_key or chat_name or "TestUser").strip() or "TestUser"
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

        normalized_thread_key = str(thread_key or chat_name or "TestUser").strip() or "TestUser"
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

        normalized_thread_key = str(thread_key or chat_name or "TestUser").strip() or "TestUser"
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

        normalized_thread_key = str(thread_key or chat_name or "TestUser").strip() or "TestUser"
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

        normalized_thread_key = str(thread_key or chat_name or "TestUser").strip() or "TestUser"
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

        normalized_thread_key = str(thread_key or chat_name or "TestUser").strip() or "TestUser"
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

    def accept_stage10(
        self,
        *,
        thread_key: str | None = None,
        chat_name: str | None = None,
        channel: str = "wechat",
        sender: str | None = None,
        iterations: int = 3,
        warmup: int = 1,
    ) -> dict[str, Any]:
        return _accept_stage10(
            self,
            thread_key=thread_key,
            chat_name=chat_name,
            channel=channel,
            sender=sender,
            iterations=iterations,
            warmup=warmup,
        )

    def _accept_stage10_impl(
        self,
        *,
        thread_key: str | None = None,
        chat_name: str | None = None,
        channel: str = "wechat",
        sender: str | None = None,
        iterations: int = 3,
        warmup: int = 1,
    ) -> dict[str, Any]:
        from .cli import _evaluate_stage10_acceptance
        from .daemon import build_daemon

        normalized_thread_key = str(thread_key or chat_name or "TestUser").strip() or "TestUser"
        normalized_chat_name = str(chat_name or thread_key or normalized_thread_key).strip() or normalized_thread_key
        normalized_sender = str(sender or normalized_chat_name).strip() or normalized_chat_name
        mode_transition = self.set_brain_mode(mode="full_brain", note="accept-stage10")
        daemon = build_daemon(str(self.config.config_path) if self.config.config_path else None)
        try:
            self_model_loop = daemon._run_self_model_refresh_cycle()
            homeostasis_loop = daemon._run_homeostasis_tick()
            goal_loop = daemon._run_goal_arbitration()
            operator_loop = daemon._run_operator_planning_cycle()
        finally:
            daemon.store.close()
            if hasattr(daemon.memory, "activation"):
                daemon.memory.activation.close()
            if hasattr(daemon.memory, "graph"):
                daemon.memory.graph.close()
        with self._memory_lock:
            if hasattr(self.memory, "clear_packet_cache"):
                self.memory.clear_packet_cache()
        engineering_state = self.engineering_state()
        goal_state = self.goal_state()
        operator_probe = self.operator_probe(thread_key=normalized_thread_key, chat_name=normalized_chat_name, channel=channel)
        operator_status = self.operator_status()
        if isinstance(operator_loop, dict):
            if isinstance(operator_loop.get("plan"), dict):
                operator_probe.update(dict(operator_loop.get("plan", {})))
                operator_probe["status"] = str(operator_loop.get("status", operator_probe.get("status", "")) or operator_probe.get("status", ""))
            else:
                loop_status = str(operator_loop.get("status", "")).strip()
                loop_blocked_reason = str(operator_loop.get("blocked_reason", "")).strip()
                if loop_status:
                    operator_probe["planning_loop_status"] = loop_status
                if loop_blocked_reason:
                    operator_probe["planning_loop_blocked_reason"] = loop_blocked_reason
                if loop_status and not str(operator_probe.get("status", "")).strip():
                    operator_probe["status"] = loop_status
                if loop_blocked_reason and not str(operator_probe.get("blocked_reason", "")).strip():
                    operator_probe["blocked_reason"] = loop_blocked_reason
        latest_operator = dict(operator_status.get("latest", {}))
        latest_operator_payload = dict(latest_operator.get("payload", {}))
        if latest_operator_payload:
            for key in ("trigger_delta", "source_goal_ids", "expected_state_gain", "budget_guard"):
                if key in latest_operator_payload and not operator_probe.get(key):
                    operator_probe[key] = latest_operator_payload.get(key)
            if not operator_probe.get("goal"):
                operator_probe["goal"] = latest_operator.get("goal", "")
        provider_status = self.provider_status()
        routing = self.processor_routing()
        usage_ledger = self.usage_ledger(limit=32)
        reply_probe = self.reply_probe(
            {
                "chat_name": normalized_chat_name,
                "thread_key": normalized_thread_key,
                "channel": channel,
                "sender": normalized_sender,
                "text": "长话短说，别绕远。",
            }
        )
        with self._memory_lock:
            if hasattr(self.memory, "record_consciousness_entry"):
                self.memory.record_consciousness_entry(
                    channel=channel,
                    thread_key=normalized_thread_key,
                    chat_name=normalized_chat_name,
                    message_id="accept-stage10-engineering-audit",
                    entry_type="stage10_engineering_audit",
                    selected_action=str(dict(reply_probe.get("selected_action", {})).get("action_type", "") or ""),
                    payload={
                        "engineering_snapshot": engineering_state,
                        "engineering_goal_snapshot": goal_state,
                        "provider_status": provider_status,
                        "routing": routing,
                        "usage_ledger": usage_ledger.get("summary", {}),
                    },
                )
                self.memory.record_consciousness_entry(
                    channel=channel,
                    thread_key=normalized_thread_key,
                    chat_name=normalized_chat_name,
                    message_id="accept-stage10-operator-plan",
                    entry_type="stage10_operator_plan",
                    selected_action=str(operator_probe.get("status", "") or ""),
                    payload={
                        "trigger_delta": dict(operator_probe.get("trigger_delta", {})),
                        "source_goal_ids": list(operator_probe.get("source_goal_ids", [])),
                        "expected_state_gain": dict(operator_probe.get("expected_state_gain", {})),
                        "budget_guard": dict(operator_probe.get("budget_guard", {})),
                    },
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
            query="为什么最近会显得有点端着，长话短说",
            thread_key=normalized_thread_key,
            chat_name=normalized_chat_name,
            channel=channel,
            sender=normalized_sender,
            iterations=iterations,
            warmup=warmup,
            target_tier="deep_recall",
        )
        report = _evaluate_stage10_acceptance(
            health=self.health(),
            mode_transition=mode_transition,
            engineering_state=engineering_state,
            goal_state=goal_state,
            operator_probe=operator_probe,
            ledger=ledger,
            usage_ledger=usage_ledger,
            provider_status=provider_status,
            routing=routing,
            reply_probe=reply_probe,
            brain_status=self.brain_status(),
            fast_benchmark=fast_benchmark,
            recall_benchmark=recall_benchmark,
            deep_benchmark=deep_benchmark,
            roadmap_registry=self.memory.roadmap_registry(),
        )
        report["transport"] = "live_http"
        report["thread_key"] = normalized_thread_key
        report["chat_name"] = normalized_chat_name
        report["sender"] = normalized_sender
        report["self_model_refresh"] = self_model_loop
        report["homeostasis_loop"] = homeostasis_loop
        report["goal_arbitration_loop"] = goal_loop
        report["operator_planning_loop"] = operator_loop
        report["operator_status"] = operator_status
        return report

    def accept_stage12(
        self,
        *,
        thread_key: str | None = None,
        chat_name: str | None = None,
        channel: str = "wechat",
        sender: str | None = None,
        iterations: int = 1,
        warmup: int = 1,
    ) -> dict[str, Any]:
        return _accept_stage12(
            self,
            thread_key=thread_key,
            chat_name=chat_name,
            channel=channel,
            sender=sender,
            iterations=iterations,
            warmup=warmup,
        )

    def _accept_stage12_impl(
        self,
        *,
        thread_key: str | None = None,
        chat_name: str | None = None,
        channel: str = "wechat",
        sender: str | None = None,
        iterations: int = 1,
        warmup: int = 1,
    ) -> dict[str, Any]:
        from .cli import _evaluate_stage12_acceptance

        normalized_thread_key = str(thread_key or chat_name or "TestUser").strip() or "TestUser"
        if channel == "wechat" and normalized_thread_key and not normalized_thread_key.startswith("wechat:") and not normalized_thread_key.endswith("@chatroom") and not normalized_thread_key.startswith("wxid_"):
            normalized_thread_key = f"wechat:{normalized_thread_key}"
        normalized_chat_name = str(chat_name or thread_key or normalized_thread_key.replace("wechat:", "", 1)).strip() or normalized_thread_key
        normalized_sender = str(sender or normalized_chat_name).strip() or normalized_chat_name
        legacy_thread_key = normalized_thread_key.removeprefix("wechat:") if normalized_thread_key.startswith("wechat:") else normalized_thread_key

        contact = self.store.ensure_contact(f"{channel}:{normalized_chat_name}", normalized_chat_name)
        thread_row, _created = self.store.ensure_thread(
            channel=channel,
            contact_id=int(contact["id"]),
            thread_key=normalized_thread_key,
            subject=normalized_chat_name,
        )

        def _acceptance_action_result(action_type: str, *, event_row_id: int, message_id: str, action_ref: str) -> dict[str, Any]:
            usage_row = self.store.record_processor_usage(
                {
                    "task_type": "accept_stage12_stub",
                    "lane": "acceptance_stub",
                    "provider": "local",
                    "model": "deterministic",
                    "thread_key": normalized_thread_key,
                    "event_id": str(event_row_id),
                    "duration_ms": 0,
                    "prompt_tokens": 8,
                    "completion_tokens": 4,
                    "total_tokens": 12,
                    "estimated": True,
                    "status": "ok",
                    "metadata": {"source": "accept_stage12", "action_type": action_type},
                }
            )
            usage_refs = [f"usage:processor_usage:{usage_row.get('id', '')}"]
            prediction = {
                "predicted_response_quality": 0.62,
                "predicted_relational_delta": 0.07,
                "predicted_identity_delta": 0.04,
                "predicted_risk": 0.08,
            }
            appraisal = self.memory.appraise_outcome(
                channel=channel,
                thread_key=normalized_thread_key,
                chat_name=normalized_chat_name,
                action_type=action_type,
                action_ref=action_ref,
                was_rewarding=0.64 if action_type != "silence" else 0.52,
                was_ignored=0.04,
                relational_delta=0.08 if action_type != "silence" else 0.02,
                identity_delta=0.05,
                future_initiative_bias=0.18,
                future_resistance_bias=0.06,
                metadata={
                    "event_row_id": event_row_id,
                    "message_id": message_id,
                    "thread_key": normalized_thread_key,
                    "selected_action": action_type,
                    "selected_prediction": prediction,
                    "predicted_outcome": prediction,
                    "usage_evidence_refs": usage_refs,
                    "usage_rows": [usage_row],
                    "usage_total_tokens": int(usage_row.get("total_tokens", 0) or 0),
                    "evidence_refs": usage_refs + [f"accept_stage12:{action_type}"],
                    "source": f"accept_stage12.{action_type}",
                },
            )
            return {
                "action": "reply" if action_type.startswith("reply") else action_type,
                "thread_key": normalized_thread_key,
                "message_id": message_id,
                "selected_action": {"action_type": action_type},
                "outcome_appraisal": appraisal,
            }

        reply_result = _acceptance_action_result("reply_once", event_row_id=1201, message_id="accept-stage12-reply", action_ref="accept-stage12-reply")
        defer_result = _acceptance_action_result("defer_reply", event_row_id=1202, message_id="accept-stage12-defer", action_ref="accept-stage12-defer")
        silence_result = _acceptance_action_result("silence", event_row_id=1203, message_id="accept-stage12-silence", action_ref="accept-stage12-silence")
        with self._memory_lock:
            if hasattr(self.memory, "clear_packet_cache"):
                self.memory.clear_packet_cache()
        subject_after_reload = self.memory.graph.subject_state(
            thread_key=normalized_thread_key,
            chat_name=normalized_chat_name,
            channel=channel,
        )
        thread_row = self.store.find_thread(channel=channel, thread_key=normalized_thread_key) or thread_row or {}
        usage_rows = [row for row in self.store.list_processor_usage(limit=24) if str(row.get("thread_key", "")).strip() in {normalized_thread_key, legacy_thread_key}]
        appraisal_rows = []
        graph = getattr(self.memory, "graph", None)
        if graph is not None and hasattr(graph, "conn"):
            appraisal_rows = [
                {
                    **dict(row),
                    "metadata": json.loads(str(row["metadata_json"] or "{}")) if str(row["metadata_json"] or "").strip() else {},
                }
                for row in graph.conn.execute(
                    """
                    SELECT * FROM outcome_appraisals
                    WHERE channel = ? AND thread_key IN (?, ?)
                    ORDER BY id DESC
                    LIMIT 12
                    """,
                    (channel, normalized_thread_key, legacy_thread_key),
                ).fetchall()
            ]
        report = _evaluate_stage12_acceptance(
            health=self.health(),
            thread_key=normalized_thread_key,
            chat_name=normalized_chat_name,
            reply_result=reply_result,
            defer_result=defer_result,
            silence_result=silence_result,
            thread_row=thread_row,
            appraisal_rows=appraisal_rows,
            usage_rows=usage_rows,
            subject_after_reload=subject_after_reload,
            helper_contracts={
                "artifact_path": _coerce_helper_artifact_path(r"D:\Holo\holo\.holo_runtime\wechat-helper\receipts\history.md"),
                "wsl_fallback_candidates": ["http://127.0.0.1:8000", "http://172.28.44.15:8000"],
            },
            roadmap_registry=self.memory.roadmap_registry(),
        )
        report["transport"] = "live_http"
        report["thread_key"] = normalized_thread_key
        report["chat_name"] = normalized_chat_name
        report["sender"] = normalized_sender
        report["reply_result"] = reply_result
        report["defer_result"] = defer_result
        report["silence_result"] = silence_result
        return report

    def accept_stage13(
        self,
        *,
        thread_key: str | None = None,
        chat_name: str | None = None,
        channel: str = "wechat",
        sender: str | None = None,
        iterations: int = 1,
        warmup: int = 1,
    ) -> dict[str, Any]:
        return _accept_stage13(
            self,
            thread_key=thread_key,
            chat_name=chat_name,
            channel=channel,
            sender=sender,
            iterations=iterations,
            warmup=warmup,
        )

    def _accept_stage13_impl(
        self,
        *,
        thread_key: str | None = None,
        chat_name: str | None = None,
        channel: str = "wechat",
        sender: str | None = None,
        iterations: int = 1,
        warmup: int = 1,
    ) -> dict[str, Any]:
        from .cli import _evaluate_stage13_acceptance

        acceptance_default = "Stage13Acceptance"
        normalized_thread_key = str(thread_key or chat_name or acceptance_default).strip() or acceptance_default
        if channel == "wechat" and normalized_thread_key and not normalized_thread_key.startswith("wechat:") and not normalized_thread_key.endswith("@chatroom") and not normalized_thread_key.startswith("wxid_"):
            normalized_thread_key = f"wechat:{normalized_thread_key}"
        normalized_chat_name = str(chat_name or thread_key or acceptance_default or normalized_thread_key.replace("wechat:", "", 1)).strip() or normalized_thread_key
        normalized_sender = str(sender or normalized_chat_name).strip() or normalized_chat_name

        before_market = self.action_market(
            thread_key=normalized_thread_key,
            chat_name=normalized_chat_name,
            channel=channel,
            query="接着说刚才那条线",
            limit=6,
        )
        subject_before = self.memory.graph.subject_state(thread_key=normalized_thread_key, chat_name=normalized_chat_name, channel=channel)
        simulation_context = {"channel": channel, "thread_key": normalized_thread_key, "chat_name": normalized_chat_name}
        simulation_intent = {
            "reply_pull": 0.7,
            "resistance_pull": 0.15,
            "continuity_pull": 0.35,
            "internal_pressure": 0.2,
            "low_signal": False,
        }
        simulation_relationship = {"continuity_score": 0.6}
        simulation_game = {"pressure_level": 0.2}
        before_reply_sim = self.memory._simulate_action_candidate(
            action={"action_type": "reply_once"},
            query="continue building this",
            intent_state=simulation_intent,
            relationship_state=simulation_relationship,
            game_state=simulation_game,
            affect_state=subject_before["affect_state"],
            drive_state=subject_before["drive_state"],
            value_state=subject_before["value_state"],
            conflict_state=subject_before["conflict_state"],
            world_state=subject_before["world_state"],
            context=simulation_context,
        )
        before_defer_sim = self.memory._simulate_action_candidate(
            action={"action_type": "defer_reply"},
            query="continue building this",
            intent_state=simulation_intent,
            relationship_state=simulation_relationship,
            game_state=simulation_game,
            affect_state=subject_before["affect_state"],
            drive_state=subject_before["drive_state"],
            value_state=subject_before["value_state"],
            conflict_state=subject_before["conflict_state"],
            world_state=subject_before["world_state"],
            context=simulation_context,
        )
        reply_bucket = self.memory.graph.action_calibration_bucket(
            action_type="reply_once",
            channel=channel,
            thread_key=normalized_thread_key,
            chat_name=normalized_chat_name,
            metadata={"low_signal": False, "question_like": False, "defer_requested": False},
        )
        defer_bucket = self.memory.graph.action_calibration_bucket(
            action_type="defer_reply",
            channel=channel,
            thread_key=normalized_thread_key,
            chat_name=normalized_chat_name,
            metadata={"low_signal": False, "question_like": False, "defer_requested": False},
        )
        before_rows = {
            "rows": [
                *self.memory.graph.list_action_calibration(
                    channel=channel,
                    thread_key=normalized_thread_key,
                    action_type="reply_once",
                    scenario_bucket=reply_bucket["scenario_bucket"],
                    limit=1,
                ),
                *self.memory.graph.list_action_calibration(
                    channel=channel,
                    thread_key=normalized_thread_key,
                    action_type="defer_reply",
                    scenario_bucket=defer_bucket["scenario_bucket"],
                    limit=1,
                ),
            ]
        }
        appraisal_payloads = [
            {
                "action_type": "reply_once",
                "action_ref": f"accept-stage13-good-{idx}",
                "was_rewarding": 0.78,
                "was_ignored": 0.04,
                "relational_delta": 0.18,
                "identity_delta": 0.08,
                "future_initiative_bias": 0.62,
                "future_resistance_bias": 0.08,
                "metadata": {
                    "predicted_outcome": {
                        "predicted_relational_delta": 0.16,
                        "predicted_identity_delta": 0.06,
                        "predicted_response_quality": 0.74,
                        "predicted_risk": 0.14,
                    },
                    "reply_latency_seconds": 90.0,
                    "initiative_success": 1.0,
                    "correction_count": 0,
                    "evidence_refs": [f"accept-stage13:good:{idx}"],
                    "source": "accept_stage13",
                },
            }
            for idx in range(max(1, warmup))
        ]
        replay_count = max(3, int(iterations or 1) * 4)
        appraisal_payloads.extend(
            [
                {
                    "action_type": "reply_once",
                    "action_ref": f"accept-stage13-bad-reply-{idx}",
                    "was_rewarding": 0.12,
                    "was_ignored": 0.84,
                    "relational_delta": -0.24,
                    "identity_delta": -0.1,
                    "future_initiative_bias": 0.0,
                    "future_resistance_bias": 0.64,
                    "metadata": {
                        "predicted_outcome": {
                            "predicted_relational_delta": 0.14,
                            "predicted_identity_delta": 0.05,
                            "predicted_response_quality": 0.72,
                            "predicted_risk": 0.16,
                        },
                        "reply_latency_seconds": 5400.0,
                        "initiative_success": 0.0,
                        "correction_count": 2,
                        "evidence_refs": [f"accept-stage13:bad-reply:{idx}"],
                        "source": "accept_stage13",
                    },
                }
                for idx in range(replay_count)
            ]
        )
        appraisal_payloads.extend(
            [
                {
                    "action_type": "defer_reply",
                    "action_ref": f"accept-stage13-good-defer-{idx}",
                    "was_rewarding": 0.66,
                    "was_ignored": 0.08,
                    "relational_delta": 0.1,
                    "identity_delta": 0.1,
                    "future_initiative_bias": 0.44,
                    "future_resistance_bias": 0.12,
                    "metadata": {
                        "predicted_outcome": {
                            "predicted_relational_delta": 0.08,
                            "predicted_identity_delta": 0.09,
                            "predicted_response_quality": 0.58,
                            "predicted_risk": 0.16,
                        },
                        "reply_latency_seconds": 300.0,
                        "initiative_success": 1.0,
                        "correction_count": 0,
                        "evidence_refs": [f"accept-stage13:good-defer:{idx}"],
                        "source": "accept_stage13",
                    },
                }
                for idx in range(replay_count)
            ]
        )
        for payload in appraisal_payloads:
            self.memory.appraise_outcome(
                channel=channel,
                thread_key=normalized_thread_key,
                chat_name=normalized_chat_name,
                **payload,
            )

        with self._memory_lock:
            if hasattr(self.memory, "clear_packet_cache"):
                self.memory.clear_packet_cache()
        after_market = self.action_market(
            thread_key=normalized_thread_key,
            chat_name=normalized_chat_name,
            channel=channel,
            query="接着说刚才那条线",
            limit=6,
        )
        subject_after_sim = self.memory.graph.subject_state(thread_key=normalized_thread_key, chat_name=normalized_chat_name, channel=channel)
        after_reply_sim = self.memory._simulate_action_candidate(
            action={"action_type": "reply_once"},
            query="continue building this",
            intent_state=simulation_intent,
            relationship_state=simulation_relationship,
            game_state=simulation_game,
            affect_state=subject_after_sim["affect_state"],
            drive_state=subject_after_sim["drive_state"],
            value_state=subject_after_sim["value_state"],
            conflict_state=subject_after_sim["conflict_state"],
            world_state=subject_after_sim["world_state"],
            context=simulation_context,
        )
        after_defer_sim = self.memory._simulate_action_candidate(
            action={"action_type": "defer_reply"},
            query="continue building this",
            intent_state=simulation_intent,
            relationship_state=simulation_relationship,
            game_state=simulation_game,
            affect_state=subject_after_sim["affect_state"],
            drive_state=subject_after_sim["drive_state"],
            value_state=subject_after_sim["value_state"],
            conflict_state=subject_after_sim["conflict_state"],
            world_state=subject_after_sim["world_state"],
            context=simulation_context,
        )
        calibration_rows = {
            "rows": [
                *self.memory.graph.list_action_calibration(
                    channel=channel,
                    thread_key=normalized_thread_key,
                    action_type="reply_once",
                    scenario_bucket=reply_bucket["scenario_bucket"],
                    limit=1,
                ),
                *self.memory.graph.list_action_calibration(
                    channel=channel,
                    thread_key=normalized_thread_key,
                    action_type="defer_reply",
                    scenario_bucket=defer_bucket["scenario_bucket"],
                    limit=1,
                ),
            ]
        }
        outcome_history = self.trace_outcome_history(
            thread_key=normalized_thread_key,
            chat_name=normalized_chat_name,
            channel=channel,
            limit=8,
        )
        prediction_trace = self.trace_action_prediction_error(
            thread_key=normalized_thread_key,
            chat_name=normalized_chat_name,
            channel=channel,
            limit=8,
        )
        subject_after_reload = self.memory.graph.subject_state(
            thread_key=normalized_thread_key,
            chat_name=normalized_chat_name,
            channel=channel,
        )
        report = _evaluate_stage13_acceptance(
            health=self.health(),
            thread_key=normalized_thread_key,
            chat_name=normalized_chat_name,
            calibration_rows=list(calibration_rows.get("rows", [])),
            before_rows=list(before_rows.get("rows", [])),
            outcome_history=list(outcome_history.get("history", [])),
            prediction_trace=prediction_trace,
            subject_after_reload=subject_after_reload,
            ranking_fixture={
                "before_top_action": "reply_once" if float(before_reply_sim.get("recommended_bias", 0.0) or 0.0) >= float(before_defer_sim.get("recommended_bias", 0.0) or 0.0) else "defer_reply",
                "after_top_action": "reply_once" if float(after_reply_sim.get("recommended_bias", 0.0) or 0.0) >= float(after_defer_sim.get("recommended_bias", 0.0) or 0.0) else "defer_reply",
                "before_market": [before_reply_sim, before_defer_sim],
                "after_market": [after_reply_sim, after_defer_sim],
            },
        )
        report["thread_key"] = normalized_thread_key
        report["chat_name"] = normalized_chat_name
        report["sender"] = normalized_sender
        report["before_market"] = before_market
        report["after_market"] = after_market
        return report

    def accept_stage14(
        self,
        *,
        source_type: str = "synthetic_fixture",
        fixture_path: str | None = None,
        thread_key: str | None = None,
        chat_name: str | None = None,
        channel: str = "wechat",
        limit: int = 8,
        artifact_dir: str | None = None,
    ) -> dict[str, Any]:
        return _accept_stage14(
            self,
            source_type=source_type,
            fixture_path=fixture_path,
            thread_key=thread_key,
            chat_name=chat_name,
            channel=channel,
            limit=limit,
            artifact_dir=artifact_dir,
        )

    def _accept_stage14_impl(
        self,
        *,
        source_type: str = "synthetic_fixture",
        fixture_path: str | None = None,
        thread_key: str | None = None,
        chat_name: str | None = None,
        channel: str = "wechat",
        limit: int = 8,
        artifact_dir: str | None = None,
    ) -> dict[str, Any]:
        from .cli import _evaluate_stage14_acceptance
        from .stage14_replay import Stage14ReplayHarness

        harness = Stage14ReplayHarness(self.memory)
        fixtures = harness.load_fixtures(
            source_type=source_type,
            fixture_path=fixture_path,
            thread_key=thread_key,
            chat_name=chat_name,
            channel=channel,
            limit=limit,
        )
        live_before: dict[str, int] = {}
        for item in fixtures:
            current_thread_key = str(item.get("thread_key", "") or "")
            current_action = str(item.get("realized_evidence", {}).get("selected_action", "") or "")
            if not current_thread_key or not current_action:
                continue
            key = f"{current_thread_key}:{current_action}"
            live_before[key] = len(
                self.memory.graph.list_action_calibration(
                    channel=str(item.get("channel", channel) or channel),
                    thread_key=current_thread_key,
                    chat_name=str(item.get("chat_name", "") or ""),
                    action_type=current_action,
                    limit=24,
                )
            )
        primary = self.memory.run_stage14_replay(
            source_type=source_type,
            fixture_path=fixture_path,
            thread_key=thread_key,
            chat_name=chat_name,
            channel=channel,
            limit=limit,
            artifact_dir=artifact_dir,
            mode="all",
        )
        with tempfile.TemporaryDirectory(prefix="holo-stage14-accept-") as secondary_artifact_dir:
            secondary = self.memory.run_stage14_replay(
                source_type=source_type,
                fixture_path=fixture_path,
                thread_key=thread_key,
                chat_name=chat_name,
                channel=channel,
                limit=limit,
                artifact_dir=secondary_artifact_dir,
                mode="all",
            )
        live_after: dict[str, int] = {}
        for item in fixtures:
            current_thread_key = str(item.get("thread_key", "") or "")
            current_action = str(item.get("realized_evidence", {}).get("selected_action", "") or "")
            if not current_thread_key or not current_action:
                continue
            key = f"{current_thread_key}:{current_action}"
            live_after[key] = len(
                self.memory.graph.list_action_calibration(
                    channel=str(item.get("channel", channel) or channel),
                    thread_key=current_thread_key,
                    chat_name=str(item.get("chat_name", "") or ""),
                    action_type=current_action,
                    limit=24,
                )
            )
        report = _evaluate_stage14_acceptance(
            health=self.health(),
            primary_report=primary,
            secondary_report=secondary,
            live_before=live_before,
            live_after=live_after,
        )
        report["primary_report"] = primary
        report["secondary_report"] = secondary
        return report

    def accept_stage16(
        self,
        *,
        run_pytest: bool = False,
        artifact_dir: str | None = None,
    ) -> dict[str, Any]:
        return _accept_stage16(self, run_pytest=run_pytest, artifact_dir=artifact_dir)

    def _accept_stage16_impl(
        self,
        *,
        run_pytest: bool = False,
        artifact_dir: str | None = None,
    ) -> dict[str, Any]:
        from .cli import _evaluate_stage16_acceptance

        stage12_report = self.accept_stage12()
        stage14_report = self.accept_stage14(artifact_dir=artifact_dir)
        return _evaluate_stage16_acceptance(
            config_path=str(self.config.config_path or ""),
            run_pytest=run_pytest,
            stage12_report=stage12_report,
            stage14_report=stage14_report,
        )

    def accept_stage17(
        self,
        *,
        thread_key: str | None = None,
        chat_name: str | None = None,
        channel: str = "wechat",
        sender: str | None = None,
        artifact_dir: str | None = None,
    ) -> dict[str, Any]:
        return _accept_stage17(
            self,
            thread_key=thread_key,
            chat_name=chat_name,
            channel=channel,
            sender=sender,
            artifact_dir=artifact_dir,
        )

    def _accept_stage17_impl(
        self,
        *,
        thread_key: str | None = None,
        chat_name: str | None = None,
        channel: str = "wechat",
        sender: str | None = None,
        artifact_dir: str | None = None,
    ) -> dict[str, Any]:
        normalized_channel = str(channel or "wechat").strip() or "wechat"
        normalized_chat_name = str(chat_name or "TestUser").strip()
        normalized_thread_key = str(thread_key or normalized_chat_name).strip()
        if normalized_channel == "wechat" and normalized_thread_key and not (
            normalized_thread_key.startswith("wechat:")
            or normalized_thread_key.startswith("wxid_")
            or normalized_thread_key.endswith("@chatroom")
        ):
            normalized_thread_key = f"wechat:{normalized_thread_key}"
        probe_turn = ChatTurn(
            chat_name=normalized_chat_name,
            text="在吗",
            sender=str(sender or normalized_chat_name),
            channel=normalized_channel,
            thread_key=normalized_thread_key,
            message_id="accept-stage17-fast",
            metadata={},
        )
        incoming = probe_turn.to_incoming_message()
        active_state = self._update_active_thread_state(
            turn=probe_turn,
            incoming=incoming,
            direction="inbound",
            event_row_id=1701,
            text=probe_turn.text,
            metadata={"source": "accept-stage17"},
        )
        context = {
            "channel": normalized_channel,
            "thread_key": normalized_thread_key,
            "incoming_thread_key": normalized_thread_key,
            "message_id": incoming.message_id,
            "chat_name": normalized_chat_name,
            "sender": str(sender or normalized_chat_name),
            "recent_history": [
                {"direction": "inbound", "body_text": "line one"},
                {"direction": "outbound", "body_text": "line two"},
                {"direction": "inbound", "body_text": "line three"},
                {"direction": "outbound", "body_text": "line four"},
            ],
            "attachments": [],
            "recall_trigger_mode": self.config.memory.recall_trigger_mode,
            "mind_budget": {
                "fast_history_messages": self.config.memory.fast_history_messages,
                "recall_history_messages": self.config.memory.recall_history_messages,
                "fast_episodic_k": self.config.memory.fast_episodic_k,
                "recall_episodic_k": self.config.memory.recall_episodic_k,
                "fast_consciousness_k": self.config.memory.fast_consciousness_k,
                "recall_consciousness_k": self.config.memory.recall_consciousness_k,
            },
            "active_thread_state": active_state,
            "event_id": "1701",
        }
        fast_started_at = time.perf_counter()
        fast_packet = self.memory.sidecar_packet(probe_turn.text, context=context)
        fast_build_ms = int((time.perf_counter() - fast_started_at) * 1000)
        fast_turn_context = TurnContext(
            channel=normalized_channel,
            thread_key=normalized_thread_key,
            chat_name=normalized_chat_name,
            sender=str(sender or normalized_chat_name),
            user_text=probe_turn.text,
            sidecar=fast_packet,
            mind_packet=fast_packet,
            attention_state=build_attention_state(probe_turn.text, channel=normalized_channel, metadata={}),
            emotion_state=dict(fast_packet.get("state", {}).get("emotion_state", {})),
            history=list(context["recent_history"]),
            metadata={"event_id": "1701"},
            capability_context={},
        )
        fast_turn_plan = build_turn_plan(fast_turn_context, self.config)
        fast_prompt = render_chat_prompt(fast_turn_context, turn_plan=fast_turn_plan)
        memory_query = "remember before our launch thread"
        recall_started_at = time.perf_counter()
        recall_packet = self.memory.sidecar_packet(
            memory_query,
            context={**context, "message_id": "accept-stage17-recall", "active_thread_state": active_state, "event_id": "1702"},
        )
        recall_build_ms = int((time.perf_counter() - recall_started_at) * 1000)
        refresh_allowed_ordinary = self._should_refresh_wechat_history(probe_turn, fast_packet)
        refresh_allowed_memory = self._should_refresh_wechat_history(
            ChatTurn(
                chat_name=normalized_chat_name,
                text="history log please",
                sender=str(sender or normalized_chat_name),
                channel=normalized_channel,
                thread_key=normalized_thread_key,
                message_id="accept-stage17-history",
                metadata={},
            ),
            recall_packet,
        )
        stage14_report = self.accept_stage14(limit=4, artifact_dir=artifact_dir)
        checks = {
            "active_thread_state_visible": bool(active_state.get("status") == "ok" and active_state.get("thread_key") == normalized_thread_key),
            "ordinary_short_turn_uses_fast_lane": str(fast_packet.get("memory_route", "")) == "active_thread"
            and bool(dict(fast_packet.get("stage17", {})).get("fast_lane")),
            "fast_lane_prompt_has_no_multiline_history": int(fast_turn_context.metadata.get("history_lines_in_prompt", 0) or 0) <= 1,
            "explicit_memory_query_escalates": str(recall_packet.get("tier", "")).strip() in {"recall", "deep_recall"}
            and str(recall_packet.get("recall_reason", "")).startswith("stage17:"),
            "active_history_refresh_demoted_for_ordinary_turn": not refresh_allowed_ordinary,
            "explicit_history_refresh_still_allowed": bool(refresh_allowed_memory),
            "action_market_first_preserved": bool(fast_packet.get("selected_action")) and bool(fast_packet.get("action_market")),
            "stage14_replay_green": str(stage14_report.get("status", "")).strip() == "pass",
        }
        metrics = dict(active_state.get("metrics", {}))
        samples = [int(item) for item in list(metrics.get("history_lines_in_prompt_samples", [])) if str(item).strip().lstrip("-").isdigit()]
        return {
            "status": "pass" if all(checks.values()) else "fail",
            "stage": "thread-resident-realtime-runtime-stage17",
            "checks": checks,
            "thread_key": normalized_thread_key,
            "chat_name": normalized_chat_name,
            "channel": normalized_channel,
            "fast_lane": {
                "tier": fast_packet.get("tier"),
                "memory_route": fast_packet.get("memory_route"),
                "retrieval_mode": fast_packet.get("retrieval_mode"),
                "history_lines_in_prompt": int(fast_turn_context.metadata.get("history_lines_in_prompt", 0) or 0),
                "turn_plan": fast_turn_plan.to_dict(),
                "prompt_excerpt": compact_text(fast_prompt, 360),
            },
            "recall_probe": {
                "query": memory_query,
                "tier": recall_packet.get("tier"),
                "recall_reason": recall_packet.get("recall_reason"),
                "memory_route": recall_packet.get("memory_route"),
            },
            "refresh_policy": {
                "ordinary_turn_blocking_refresh": refresh_allowed_ordinary,
                "explicit_history_blocking_refresh": refresh_allowed_memory,
            },
            "metrics": {
                "fast_lane_hit_rate": 1.0 if checks["ordinary_short_turn_uses_fast_lane"] else 0.0,
                "recall_escalation_rate": 1.0 if checks["explicit_memory_query_escalates"] else 0.0,
                "active_history_refresh_rate": 0.0 if not refresh_allowed_ordinary else 1.0,
                "avg_history_lines_in_prompt": (
                    round(sum(samples) / len(samples), 4)
                    if samples
                    else float(fast_turn_context.metadata.get("history_lines_in_prompt", 0) or 0)
                ),
                "thread_active_state_cache_hit_ratio": 1.0 if active_state.get("cache_warmth") in {"warm", "seeded"} else 0.0,
                "p50_inspect_build_latency_ms": min(fast_build_ms, recall_build_ms),
                "p95_inspect_build_latency_ms": max(fast_build_ms, recall_build_ms),
            },
            "active_thread_state": active_state,
            "stage14": {"status": stage14_report.get("status"), "checks": stage14_report.get("checks", {})},
        }

    def show_fast_path_metrics(
        self,
        *,
        thread_key: str | None = None,
        chat_name: str | None = None,
        channel: str = "wechat",
    ) -> dict[str, Any]:
        return self.memory.fast_path_metrics(thread_key=thread_key, chat_name=chat_name, channel=channel)

    def show_predictive_continuity(
        self,
        *,
        thread_key: str | None = None,
        chat_name: str | None = None,
        channel: str = "wechat",
    ) -> dict[str, Any]:
        return self.memory.predictive_continuity(thread_key=thread_key, chat_name=chat_name, channel=channel)

    def show_scene_state(
        self,
        *,
        thread_key: str | None = None,
        chat_name: str | None = None,
        channel: str = "wechat",
    ) -> dict[str, Any]:
        return self.memory.scene_state(thread_key=thread_key, chat_name=chat_name, channel=channel)

    def trace_predicted_branches(
        self,
        *,
        thread_key: str | None = None,
        chat_name: str | None = None,
        channel: str = "wechat",
    ) -> dict[str, Any]:
        return self.memory.trace_predicted_branches(thread_key=thread_key, chat_name=chat_name, channel=channel)

    def trace_scene_compression(
        self,
        *,
        thread_key: str | None = None,
        chat_name: str | None = None,
        channel: str = "wechat",
    ) -> dict[str, Any]:
        return self.memory.trace_scene_compression(thread_key=thread_key, chat_name=chat_name, channel=channel)

    def show_continuity_budget(
        self,
        *,
        channel: str = "wechat",
    ) -> dict[str, Any]:
        return self.memory.show_continuity_budget(channel=channel)

    def show_dense_working_set(
        self,
        *,
        channel: str = "wechat",
    ) -> dict[str, Any]:
        return self.memory.show_dense_working_set(channel=channel)

    def show_task_world(
        self,
        *,
        thread_key: str | None = None,
        chat_name: str | None = None,
        channel: str = "wechat",
        limit: int = 12,
        include_inactive: bool = False,
    ) -> dict[str, Any]:
        return self.memory.show_task_world(
            thread_key=thread_key,
            chat_name=chat_name,
            channel=channel,
            limit=limit,
            include_inactive=include_inactive,
        )

    def show_situational_field(
        self,
        *,
        query: str = "",
        thread_key: str | None = None,
        chat_name: str | None = None,
        channel: str = "wechat",
    ) -> dict[str, Any]:
        return self.memory.show_situational_field(
            query=query,
            thread_key=thread_key,
            chat_name=chat_name,
            channel=channel,
        )

    def trace_visual_field(
        self,
        *,
        thread_key: str | None = None,
        chat_name: str | None = None,
        channel: str = "wechat",
    ) -> dict[str, Any]:
        return self.memory.trace_visual_field(thread_key=thread_key, chat_name=chat_name, channel=channel)

    def trace_inquiry_shaping(
        self,
        *,
        query: str,
        thread_key: str | None = None,
        chat_name: str | None = None,
        channel: str = "wechat",
        limit: int = 8,
    ) -> dict[str, Any]:
        return self.memory.trace_inquiry_shaping(
            query=query,
            thread_key=thread_key,
            chat_name=chat_name,
            channel=channel,
            limit=limit,
        )

    def trace_world_object(self, *, object_id: str) -> dict[str, Any]:
        return self.memory.trace_world_object(object_id=object_id)

    def trace_thread_object_links(
        self,
        *,
        thread_key: str | None = None,
        chat_name: str | None = None,
        channel: str = "wechat",
        limit: int = 12,
    ) -> dict[str, Any]:
        return self.memory.trace_thread_object_links(
            thread_key=thread_key,
            chat_name=chat_name,
            channel=channel,
            limit=limit,
        )

    def trace_thread_pulse(
        self,
        *,
        thread_key: str | None = None,
        chat_name: str | None = None,
        channel: str = "wechat",
        limit: int = 12,
    ) -> dict[str, Any]:
        return self.memory.trace_thread_pulse(thread_key=thread_key, chat_name=chat_name, channel=channel, limit=limit)

    def trace_reflex_routing(
        self,
        *,
        thread_key: str | None = None,
        chat_name: str | None = None,
        channel: str = "wechat",
        query: str = "",
    ) -> dict[str, Any]:
        trace = self.memory.trace_reflex_routing(
            query=query,
            thread_key=thread_key,
            chat_name=chat_name,
            channel=channel,
        )
        packet = {
            "tier": trace.get("tier", ""),
            "memory_route": trace.get("memory_route", ""),
            "active_thread_state": {
                "predictive_continuity": dict(trace.get("predictive_continuity", {})),
                "scene_state": dict(trace.get("scene_state", {})),
            },
            "stage18": dict(trace.get("stage18", {})),
            "stage24": dict(trace.get("stage24", {})),
            "selected_action": dict(trace.get("selected_action", {})),
        }
        turn_context = TurnContext(
            channel=channel,
            thread_key=str(trace.get("thread_key", thread_key or "") or ""),
            chat_name=str(trace.get("chat_name", chat_name or thread_key or "") or ""),
            sender=str(chat_name or thread_key or ""),
            user_text=query,
            sidecar=packet,
            mind_packet=packet,
            attention_state=build_attention_state(query, channel=channel, metadata={}),
            emotion_state={},
            history=[],
            metadata={},
            capability_context={},
        )
        turn_plan = build_turn_plan(turn_context, self.config)
        lane, lane_reason, reflex_candidate = _select_reply_lane(turn_context, turn_plan, self.config)
        trace["generation_lane"] = lane
        trace["generation_lane_reason"] = lane_reason
        trace["reflex_micro_fast_candidate"] = reflex_candidate
        trace["turn_plan"] = turn_plan.to_dict()
        return trace

    def accept_stage18(
        self,
        *,
        thread_key: str | None = None,
        chat_name: str | None = None,
        channel: str = "wechat",
        sender: str | None = None,
        artifact_dir: str | None = None,
    ) -> dict[str, Any]:
        return _accept_stage18(
            self,
            thread_key=thread_key,
            chat_name=chat_name,
            channel=channel,
            sender=sender,
            artifact_dir=artifact_dir,
        )

    def _accept_stage18_impl(
        self,
        *,
        thread_key: str | None = None,
        chat_name: str | None = None,
        channel: str = "wechat",
        sender: str | None = None,
        artifact_dir: str | None = None,
    ) -> dict[str, Any]:
        normalized_channel = str(channel or "wechat").strip() or "wechat"
        normalized_chat_name = str(chat_name or "TestUser").strip()
        normalized_thread_key = str(thread_key or normalized_chat_name).strip()
        if normalized_channel == "wechat" and normalized_thread_key and not (
            normalized_thread_key.startswith("wechat:")
            or normalized_thread_key.startswith("wxid_")
            or normalized_thread_key.endswith("@chatroom")
        ):
            normalized_thread_key = f"wechat:{normalized_thread_key}"
        probe_text = "still here?"
        probe_turn = ChatTurn(
            chat_name=normalized_chat_name,
            text=probe_text,
            sender=str(sender or normalized_chat_name),
            channel=normalized_channel,
            thread_key=normalized_thread_key,
            message_id="accept-stage18-reflex",
            metadata={},
        )
        incoming = probe_turn.to_incoming_message()
        active_state = self._update_active_thread_state(
            turn=probe_turn,
            incoming=incoming,
            direction="inbound",
            event_row_id=1801,
            text=probe_turn.text,
            metadata={"source": "accept-stage18"},
        )
        context = {
            "channel": normalized_channel,
            "thread_key": normalized_thread_key,
            "incoming_thread_key": normalized_thread_key,
            "message_id": incoming.message_id,
            "chat_name": normalized_chat_name,
            "sender": str(sender or normalized_chat_name),
            "recent_history": [
                {"direction": "inbound", "body_text": "old line one"},
                {"direction": "outbound", "body_text": "old line two"},
                {"direction": "inbound", "body_text": "old line three"},
            ],
            "attachments": [],
            "active_thread_state": active_state,
            "event_id": "1801",
        }
        fast_packet = self.memory.sidecar_packet(probe_text, context=context)
        fast_turn_context = TurnContext(
            channel=normalized_channel,
            thread_key=normalized_thread_key,
            chat_name=normalized_chat_name,
            sender=str(sender or normalized_chat_name),
            user_text=probe_text,
            sidecar=fast_packet,
            mind_packet=fast_packet,
            attention_state=build_attention_state(probe_text, channel=normalized_channel, metadata={}),
            emotion_state=dict(fast_packet.get("state", {}).get("emotion_state", {})),
            history=list(context["recent_history"]),
            metadata={"event_id": "1801"},
            capability_context={},
        )
        fast_turn_plan = build_turn_plan(fast_turn_context, self.config)
        fast_prompt = render_chat_prompt(fast_turn_context, turn_plan=fast_turn_plan)
        generation_lane, lane_reason, reflex_candidate = _select_reply_lane(fast_turn_context, fast_turn_plan, self.config)

        memory_query = "remember previous history"
        recall_packet = self.memory.sidecar_packet(
            memory_query,
            context={**context, "message_id": "accept-stage18-recall", "active_thread_state": active_state, "event_id": "1802"},
        )
        low_conf_state = dict(active_state)
        low_conf_predictive = dict(low_conf_state.get("predictive_continuity", {}))
        low_conf_predictive["active_prediction_confidence"] = 0.1
        low_conf_predictive["reflex_eligibility"] = False
        low_conf_state["predictive_continuity"] = low_conf_predictive
        low_conf_packet = self.memory.sidecar_packet(
            probe_text,
            context={**context, "message_id": "accept-stage18-low-confidence", "active_thread_state": low_conf_state, "event_id": "1803"},
        )
        reloaded_state = self.memory.active_thread_state(
            channel=normalized_channel,
            thread_key=normalized_thread_key,
            chat_name=normalized_chat_name,
        )
        stage17_report = self.accept_stage17(
            thread_key=normalized_thread_key,
            chat_name=normalized_chat_name,
            channel=normalized_channel,
            sender=sender,
            artifact_dir=artifact_dir,
        )
        predictive = dict(reloaded_state.get("predictive_continuity", {}))
        checks = {
            "predictive_fields_visible": all(
                key in predictive
                for key in (
                    "predicted_next_user_act",
                    "predicted_reply_pressure",
                    "likely_reference_targets",
                    "expected_social_valence",
                    "reflex_eligibility",
                    "turn_rhythm",
                    "freshness_at",
                    "active_prediction_confidence",
                )
            ),
            "ordinary_short_turn_routes_generation_micro_fast": generation_lane == "micro_fast"
            and bool(reflex_candidate)
            and str(fast_packet.get("memory_route", "")) == "active_thread",
            "explicit_memory_query_escalates": str(recall_packet.get("tier", "")).strip() in {"recall", "deep_recall"}
            and str(recall_packet.get("recall_reason", "")).startswith("stage17:"),
            "low_confidence_alone_does_not_deep_recall": str(low_conf_packet.get("tier", "")).strip() != "deep_recall",
            "predictive_continuity_persisted": bool(predictive.get("freshness_at"))
            and "active_prediction_confidence" in reloaded_state,
            "fast_prompt_uses_predictive_before_history": "predictive_continuity" in fast_prompt
            and "old line two" not in fast_prompt
            and int(fast_turn_context.metadata.get("history_lines_in_prompt", 0) or 0) <= 1,
            "action_market_first_preserved": bool(fast_packet.get("selected_action")) and bool(fast_packet.get("action_market")),
            "stage17_acceptance_green": str(stage17_report.get("status", "")).strip() == "pass",
        }
        return {
            "status": "pass" if all(checks.values()) else "fail",
            "stage": "dual-speed-reflex-and-predictive-continuity-stage18",
            "checks": checks,
            "thread_key": normalized_thread_key,
            "chat_name": normalized_chat_name,
            "channel": normalized_channel,
            "generation_lane": {
                "lane": generation_lane,
                "reason": lane_reason,
                "reflex_micro_fast_candidate": reflex_candidate,
                "turn_plan": fast_turn_plan.to_dict(),
            },
            "fast_packet": {
                "tier": fast_packet.get("tier"),
                "memory_route": fast_packet.get("memory_route"),
                "retrieval_mode": fast_packet.get("retrieval_mode"),
                "stage18": dict(fast_packet.get("stage18", {})),
                "selected_action": dict(fast_packet.get("selected_action", {})),
                "history_lines_in_prompt": int(fast_turn_context.metadata.get("history_lines_in_prompt", 0) or 0),
                "predictive_lines_in_prompt": int(fast_turn_context.metadata.get("predictive_lines_in_prompt", 0) or 0),
                "prompt_excerpt": compact_text(fast_prompt, 360),
            },
            "recall_probe": {
                "query": memory_query,
                "tier": recall_packet.get("tier"),
                "recall_reason": recall_packet.get("recall_reason"),
                "memory_route": recall_packet.get("memory_route"),
            },
            "low_confidence_probe": {
                "tier": low_conf_packet.get("tier"),
                "recall_reason": low_conf_packet.get("recall_reason"),
                "memory_route": low_conf_packet.get("memory_route"),
            },
            "predictive_continuity": predictive,
            "active_thread_state": reloaded_state,
            "stage17": {"status": stage17_report.get("status"), "checks": stage17_report.get("checks", {})},
        }

    def show_attention_frontier(
        self,
        *,
        channel: str | None = None,
        limit: int = 8,
        include_stale: bool = False,
    ) -> dict[str, Any]:
        return self.memory.attention_frontier(channel=channel, limit=limit, include_stale=include_stale)

    def trace_wake_reasons(
        self,
        *,
        thread_key: str | None = None,
        chat_name: str | None = None,
        channel: str = "wechat",
    ) -> dict[str, Any]:
        return self.memory.trace_wake_reasons(thread_key=thread_key, chat_name=chat_name, channel=channel)

    def show_thread_warmth(
        self,
        *,
        thread_key: str | None = None,
        chat_name: str | None = None,
        channel: str = "wechat",
    ) -> dict[str, Any]:
        return self.memory.thread_warmth(thread_key=thread_key, chat_name=chat_name, channel=channel)

    def show_open_loops(
        self,
        *,
        thread_key: str | None = None,
        chat_name: str | None = None,
        channel: str = "wechat",
        include_inactive: bool = False,
    ) -> dict[str, Any]:
        return self.memory.show_open_loops(thread_key=thread_key, chat_name=chat_name, channel=channel, include_inactive=include_inactive)

    def show_commitments(
        self,
        *,
        thread_key: str | None = None,
        chat_name: str | None = None,
        channel: str = "wechat",
        include_inactive: bool = False,
    ) -> dict[str, Any]:
        return self.memory.show_commitments(thread_key=thread_key, chat_name=chat_name, channel=channel, include_inactive=include_inactive)

    def trace_resume_candidate(
        self,
        *,
        thread_key: str | None = None,
        chat_name: str | None = None,
        channel: str = "wechat",
        include_inactive: bool = False,
    ) -> dict[str, Any]:
        return self.memory.trace_resume_candidate(thread_key=thread_key, chat_name=chat_name, channel=channel, include_inactive=include_inactive)

    def accept_stage19(
        self,
        *,
        thread_key: str | None = None,
        chat_name: str | None = None,
        channel: str = "wechat",
        sender: str | None = None,
        artifact_dir: str | None = None,
    ) -> dict[str, Any]:
        return _accept_stage19(
            self,
            thread_key=thread_key,
            chat_name=chat_name,
            channel=channel,
            sender=sender,
            artifact_dir=artifact_dir,
        )

    def accept_stage20(
        self,
        *,
        thread_key: str | None = None,
        chat_name: str | None = None,
        channel: str = "wechat",
        sender: str | None = None,
        artifact_dir: str | None = None,
    ) -> dict[str, Any]:
        return _accept_stage20(
            self,
            thread_key=thread_key,
            chat_name=chat_name,
            channel=channel,
            sender=sender,
            artifact_dir=artifact_dir,
        )

    def accept_stage21(
        self,
        *,
        thread_key: str | None = None,
        chat_name: str | None = None,
        channel: str = "wechat",
        sender: str | None = None,
        artifact_dir: str | None = None,
    ) -> dict[str, Any]:
        return _accept_stage21(
            self,
            thread_key=thread_key,
            chat_name=chat_name,
            channel=channel,
            sender=sender,
            artifact_dir=artifact_dir,
        )

    def _accept_stage19_impl(
        self,
        *,
        thread_key: str | None = None,
        chat_name: str | None = None,
        channel: str = "wechat",
        sender: str | None = None,
        artifact_dir: str | None = None,
    ) -> dict[str, Any]:
        normalized_channel = str(channel or "wechat").strip() or "wechat"
        normalized_chat_name = str(chat_name or "TestUser").strip()
        normalized_thread_key = str(thread_key or normalized_chat_name).strip()
        if normalized_channel == "wechat" and normalized_thread_key and not (
            normalized_thread_key.startswith("wechat:")
            or normalized_thread_key.startswith("wxid_")
            or normalized_thread_key.endswith("@chatroom")
        ):
            normalized_thread_key = f"wechat:{normalized_thread_key}"

        self.memory.rag.archive_turn(
            "stage19 warm frontier seed",
            "stage19 keeps the unfinished line warm without copying history",
            source="accept_stage19.frontier_seed",
            tags=["wechat", "stage19"],
            turn_id=f"accept-stage19-{stable_digest(normalized_thread_key, normalized_chat_name)[:10]}",
            metadata={"channel": normalized_channel, "thread_key": normalized_thread_key, "chat_name": normalized_chat_name},
        )
        sync_report = self.memory.graph.sync_thread(channel=normalized_channel, thread_key=normalized_thread_key, chat_name=normalized_chat_name)
        inspect = self.memory.graph.inspect_graph(thread_key=normalized_thread_key, chat_name=normalized_chat_name, channel=normalized_channel, limit=6)
        archive_node = next((dict(node) for node in inspect.get("nodes", []) if str(node.get("source_store", "")) == "archive"), {})
        stream_report = self.memory.record_stream_run(
            "association_stream",
            status="ok",
            note="stage19_acceptance",
            payload={
                "thoughts": [
                    {
                        "channel": normalized_channel,
                        "thread_key": normalized_thread_key,
                        "chat_name": normalized_chat_name,
                        "motif": "stage19_continuity",
                        "source_archive_id": str(archive_node.get("source_id", archive_node.get("id", "")) or ""),
                    }
                ],
                "selected_memory_ids": [str(archive_node.get("source_id", archive_node.get("id", "")) or "")],
            },
        )
        frontier = self.show_attention_frontier(channel=normalized_channel, limit=8)
        warmth = self.show_thread_warmth(thread_key=normalized_thread_key, chat_name=normalized_chat_name, channel=normalized_channel)
        wake_trace = self.trace_wake_reasons(thread_key=normalized_thread_key, chat_name=normalized_chat_name, channel=normalized_channel)

        warm_query = "still here?"
        context = {
            "channel": normalized_channel,
            "thread_key": normalized_thread_key,
            "incoming_thread_key": normalized_thread_key,
            "message_id": "accept-stage19-warm-reentry",
            "chat_name": normalized_chat_name,
            "sender": str(sender or normalized_chat_name),
            "attachments": [],
            "event_id": "1901",
        }
        started_at = time.perf_counter()
        warm_packet = self.memory.sidecar_packet(warm_query, context=context)
        warm_build_ms = int((time.perf_counter() - started_at) * 1000)
        warm_turn_context = TurnContext(
            channel=normalized_channel,
            thread_key=normalized_thread_key,
            chat_name=normalized_chat_name,
            sender=str(sender or normalized_chat_name),
            user_text=warm_query,
            sidecar=warm_packet,
            mind_packet=warm_packet,
            attention_state=build_attention_state(warm_query, channel=normalized_channel, metadata={}),
            emotion_state=dict(warm_packet.get("state", {}).get("emotion_state", {})),
            history=[{"direction": "inbound", "body_text": warm_query}],
            metadata={"event_id": "1901"},
            capability_context={},
        )
        warm_turn_plan = build_turn_plan(warm_turn_context, self.config)
        generation_lane, lane_reason, reflex_candidate = _select_reply_lane(warm_turn_context, warm_turn_plan, self.config)

        memory_query = "remember previous history"
        recall_packet = self.memory.sidecar_packet(
            memory_query,
            context={**context, "message_id": "accept-stage19-memory-recall", "event_id": "1902"},
        )

        restore_stale_after = str(dict(warmth.get("frontier_item", {})).get("stale_after", "") or "")
        stale_at = "2000-01-01T00:00:00Z"
        with self.memory.graph._lock:
            self.memory.graph.conn.execute(
                "UPDATE attention_frontier SET stale_after = ? WHERE channel = ? AND canonical_thread_key = ?",
                (stale_at, normalized_channel, normalized_thread_key),
            )
            self.memory.graph.conn.commit()
        self.memory.clear_packet_cache()
        decayed_warmth = self.show_thread_warmth(thread_key=normalized_thread_key, chat_name=normalized_chat_name, channel=normalized_channel)
        decayed_packet = self.memory.sidecar_packet(
            warm_query,
            context={**context, "message_id": "accept-stage19-decayed", "event_id": "1903"},
        )
        if restore_stale_after and restore_stale_after != stale_at:
            with self.memory.graph._lock:
                self.memory.graph.conn.execute(
                    "UPDATE attention_frontier SET stale_after = ? WHERE channel = ? AND canonical_thread_key = ?",
                    (restore_stale_after, normalized_channel, normalized_thread_key),
                )
                self.memory.graph.conn.commit()
            self.memory.clear_packet_cache()
        stage18_report = self.accept_stage18(
            thread_key=normalized_thread_key,
            chat_name=normalized_chat_name,
            channel=normalized_channel,
            sender=sender,
            artifact_dir=artifact_dir,
        )
        checks = {
            "frontier_persisted_and_inspectable": any(
                str(item.get("canonical_thread_key", "")) == normalized_thread_key
                for item in frontier.get("entries", [])
            ),
            "frontier_influenced_by_allowed_stream": bool(stream_report.get("influence", {}).get("frontier_updates"))
            and str(stream_report.get("stream_name", "")) in {"maintenance_stream", "association_stream", "social_stream", "deep_dream_cycle"},
            "warm_reentry_uses_active_reflex_path": str(warm_packet.get("memory_route", "")) == "active_thread"
            and bool(dict(warm_packet.get("stage19", {})).get("frontier_used_for_thread", False)),
            "ordinary_short_turn_generation_can_stay_reflex": generation_lane in {"micro_fast", "subject_main"}
            and str(warm_packet.get("memory_route", "")) == "active_thread",
            "ordinary_turn_not_blocked_by_stream_work": warm_build_ms < 750
            and str(warm_packet.get("retrieval_mode", "")) == "active-thread-fast",
            "thread_warmth_decays_to_cold": str(decayed_warmth.get("thread_warmth", "")) == "cold"
            and bool(decayed_warmth.get("stale", False))
            and not bool(dict(decayed_packet.get("stage19", {})).get("frontier_used_for_thread", False)),
            "explicit_memory_query_escalates": str(recall_packet.get("tier", "")).strip() in {"recall", "deep_recall"}
            and str(recall_packet.get("recall_reason", "")).startswith("stage17:"),
            "stage18_acceptance_green": str(stage18_report.get("status", "")).strip() == "pass",
        }
        return {
            "status": "pass" if all(checks.values()) else "fail",
            "stage": "bounded-background-continuity-and-attention-frontier-stage19",
            "checks": checks,
            "thread_key": normalized_thread_key,
            "chat_name": normalized_chat_name,
            "channel": normalized_channel,
            "stream_report": stream_report,
            "sync_report": sync_report,
            "attention_frontier": frontier,
            "thread_warmth": warmth,
            "wake_trace": wake_trace,
            "warm_reentry": {
                "tier": warm_packet.get("tier"),
                "memory_route": warm_packet.get("memory_route"),
                "retrieval_mode": warm_packet.get("retrieval_mode"),
                "stage19": dict(warm_packet.get("stage19", {})),
                "generation_lane": generation_lane,
                "generation_lane_reason": lane_reason,
                "reflex_micro_fast_candidate": reflex_candidate,
                "turn_plan": warm_turn_plan.to_dict(),
                "build_ms": warm_build_ms,
            },
            "recall_probe": {
                "query": memory_query,
                "tier": recall_packet.get("tier"),
                "recall_reason": recall_packet.get("recall_reason"),
                "memory_route": recall_packet.get("memory_route"),
            },
            "decay_probe": {
                "thread_warmth": decayed_warmth,
                "stage19": dict(decayed_packet.get("stage19", {})),
            },
            "stage18": {"status": stage18_report.get("status"), "checks": stage18_report.get("checks", {})},
        }

    def _accept_stage20_impl(
        self,
        *,
        thread_key: str | None = None,
        chat_name: str | None = None,
        channel: str = "wechat",
        sender: str | None = None,
        artifact_dir: str | None = None,
    ) -> dict[str, Any]:
        normalized_channel = str(channel or "wechat").strip() or "wechat"
        normalized_chat_name = str(chat_name or "TestUser").strip()
        normalized_thread_key = str(thread_key or normalized_chat_name).strip()
        if normalized_channel == "wechat" and normalized_thread_key and not (
            normalized_thread_key.startswith("wechat:")
            or normalized_thread_key.startswith("wxid_")
            or normalized_thread_key.endswith("@chatroom")
        ):
            normalized_thread_key = f"wechat:{normalized_thread_key}"
        run_id = stable_digest(normalized_thread_key, normalized_chat_name, utc_now())[:12]
        defer_event_row_id = 200000 + (int(run_id[:6], 16) % 700000)
        reentry_event_row_id = defer_event_row_id + 1
        contact = self.store.ensure_contact(normalized_thread_key if normalized_channel == "wechat" else f"{normalized_channel}:{normalized_thread_key}", normalized_chat_name)
        thread, _created = self.store.ensure_thread(
            channel=normalized_channel,
            contact_id=int(contact["id"]),
            thread_key=normalized_thread_key,
            subject=normalized_chat_name,
        )
        incoming = IncomingMessage(
            message_id=f"accept-stage20-defer-{run_id}",
            thread_key=normalized_thread_key,
            subject=normalized_chat_name,
            sender_email=normalized_thread_key,
            sender_name=str(sender or normalized_chat_name),
            body_text="please reply later",
            channel=normalized_channel,
        )
        stored = self.store.record_inbound(incoming)["message"]
        turn = ChatTurn(
            chat_name=normalized_chat_name,
            text="please reply later",
            sender=str(sender or normalized_chat_name),
            channel=normalized_channel,
            thread_key=normalized_thread_key,
            message_id=str(incoming.message_id),
            metadata={},
        )
        selected_defer = {"action_type": "defer_reply", "score": 0.91, "why_now": "accept_stage20_defer"}
        deferred_job_id = self._schedule_deferred_reply(
            thread=thread,
            contact=contact,
            stored_message=stored,
            turn=turn,
            selected_action=selected_defer,
            defer_reason="accept_stage20_deferred_reply",
            event_row_id=defer_event_row_id,
        )
        duplicate_job_id = self._schedule_deferred_reply(
            thread=thread,
            contact=contact,
            stored_message=stored,
            turn=turn,
            selected_action=selected_defer,
            defer_reason="accept_stage20_deferred_reply",
            event_row_id=defer_event_row_id,
        )

        due_resume = self.memory.graph.upsert_temporal_item(
            item_type="resume_candidate",
            channel=normalized_channel,
            thread_key=normalized_thread_key,
            chat_name=normalized_chat_name,
            confidence=0.76,
            source_event_id="accept-stage20-resume",
            source_action_ref=f"resume:{run_id}",
            source_action_type="history_refresh",
            due_at="2000-01-01T00:00:00Z",
            revisit_after="2000-01-01T00:00:00Z",
            resume_cue="we were talking about the postponed line",
            dedupe_key=f"stage20-resume:{run_id}",
            status="scheduled",
            metadata={"source": "accept_stage20", "evidence_refs": [f"accept_stage20:{run_id}"]},
        )
        other_thread = self.memory.graph.upsert_temporal_item(
            item_type="interruption_marker",
            channel=normalized_channel,
            thread_key=f"{normalized_thread_key}-other",
            chat_name=f"{normalized_chat_name}-other",
            confidence=0.77,
            source_event_id="accept-stage20-other",
            source_action_ref=f"other:{run_id}",
            source_action_type="external_lookup",
            due_at="2000-01-01T00:00:00Z",
            revisit_after="2000-01-01T00:00:00Z",
            resume_cue="other thread should stay isolated",
            dedupe_key=f"stage20-other:{run_id}",
            status="scheduled",
            metadata={"source": "accept_stage20", "evidence_refs": [f"accept_stage20:{run_id}:other"]},
        )
        expired = self.memory.graph.upsert_temporal_item(
            item_type="open_loop",
            channel=normalized_channel,
            thread_key=normalized_thread_key,
            chat_name=normalized_chat_name,
            confidence=0.52,
            source_event_id="accept-stage20-expired",
            source_action_ref=f"expired:{run_id}",
            source_action_type="reply_once",
            due_at="1999-01-01T00:00:00Z",
            revisit_after="1999-01-01T00:00:00Z",
            revisit_before="2000-01-01T00:00:00Z",
            resume_cue="expired line should not steer reply",
            dedupe_key=f"stage20-expired:{run_id}",
            status="open",
            metadata={"source": "accept_stage20", "evidence_refs": [f"accept_stage20:{run_id}:expired"]},
        )
        self.memory.clear_packet_cache()

        self.memory.update_active_thread_state(
            channel=normalized_channel,
            thread_key=normalized_thread_key,
            chat_name=normalized_chat_name,
            direction="inbound",
            text="we were talking about the postponed line",
            message_id=f"accept-stage20-reentry-{run_id}",
            event_row_id=reentry_event_row_id,
            metadata={"source": "accept_stage20"},
        )
        temporal = self.memory.temporal_state(thread_key=normalized_thread_key, chat_name=normalized_chat_name, channel=normalized_channel, include_inactive=True)
        open_loops = self.show_open_loops(thread_key=normalized_thread_key, chat_name=normalized_chat_name, channel=normalized_channel)
        commitments = self.show_commitments(thread_key=normalized_thread_key, chat_name=normalized_chat_name, channel=normalized_channel)
        resume_trace = self.trace_resume_candidate(thread_key=normalized_thread_key, chat_name=normalized_chat_name, channel=normalized_channel)

        packet = self.memory.sidecar_packet(
            "we were talking about the postponed line",
            context={
                "channel": normalized_channel,
                "thread_key": normalized_thread_key,
                "chat_name": normalized_chat_name,
                "sender": str(sender or normalized_chat_name),
                "attachments": [],
                "message_id": f"accept-stage20-packet-{run_id}",
                "event_id": "2003",
            },
        )
        explicit_packet = self.memory.sidecar_packet(
            "remember previous history",
            context={
                "channel": normalized_channel,
                "thread_key": normalized_thread_key,
                "chat_name": normalized_chat_name,
                "sender": str(sender or normalized_chat_name),
                "attachments": [],
                "message_id": f"accept-stage20-memory-{run_id}",
                "event_id": "2004",
            },
        )
        close_report = self.memory.graph.close_temporal_items(
            channel=normalized_channel,
            thread_key=normalized_thread_key,
            chat_name=normalized_chat_name,
            source_action_ref=f"resume:{run_id}",
            status="fulfilled",
            reason="accept_stage20_fulfilled",
        )
        self.memory.clear_packet_cache()
        fulfilled_packet = self.memory.sidecar_packet(
            "still here?",
            context={
                "channel": normalized_channel,
                "thread_key": normalized_thread_key,
                "chat_name": normalized_chat_name,
                "sender": str(sender or normalized_chat_name),
                "attachments": [],
                "message_id": f"accept-stage20-fulfilled-{run_id}",
                "event_id": "2005",
            },
        )
        stage19_report = self.accept_stage19(
            thread_key=normalized_thread_key,
            chat_name=normalized_chat_name,
            channel=normalized_channel,
            sender=sender,
            artifact_dir=artifact_dir,
        )
        cleanup_report: dict[str, Any] = {}
        if deferred_job_id > 0:
            self.store.block_job(deferred_job_id, "accept_stage20_probe_cleanup")
            cleanup_report["deferred_job_id"] = deferred_job_id
            cleanup_report["deferred_temporal"] = self.memory.graph.close_temporal_items(
                channel=normalized_channel,
                thread_key=normalized_thread_key,
                chat_name=normalized_chat_name,
                source_action_ref=str(deferred_job_id),
                status="canceled",
                reason="accept_stage20_probe_cleanup",
            )
        cleanup_report["reentry_temporal"] = self.memory.graph.close_temporal_items(
            channel=normalized_channel,
            thread_key=normalized_thread_key,
            chat_name=normalized_chat_name,
            source_event_id=str(reentry_event_row_id),
            status="canceled",
            reason="accept_stage20_probe_cleanup",
        )
        cleanup_report["other_thread_temporal"] = self.memory.graph.close_temporal_items(
            channel=normalized_channel,
            thread_key=f"{normalized_thread_key}-other",
            chat_name=f"{normalized_chat_name}-other",
            source_action_ref=f"other:{run_id}",
            status="canceled",
            reason="accept_stage20_probe_cleanup",
        )
        self.memory.clear_packet_cache()
        commitment_items = list(commitments.get("commitments", [])) + list(commitments.get("deferred_intentions", []))
        checks = {
            "temporal_state_persisted_and_grouped": bool(temporal.get("open_loops") or temporal.get("resume_candidates") or temporal.get("deferred_intentions")),
            "defer_reply_created_one_commitment_and_one_queue_job": deferred_job_id > 0
            and duplicate_job_id == deferred_job_id
            and any(int(item.get("queue_job_id", 0) or 0) == deferred_job_id for item in commitment_items),
            "due_resume_enters_packet_before_heavy_recall": bool(dict(packet.get("stage20", {})).get("temporal_visible", False))
            and bool(dict(packet.get("stage20", {})).get("commitment_due", False))
            and str(packet.get("memory_route", "")) in {"active_thread", "graph", "hybrid"},
            "action_market_owns_recovery": any(
                bool(dict(item.get("temporal_context", {})).get("due", False))
                for item in list(packet.get("action_market", []))
            ),
            "interleaved_threads_stay_isolated": str(other_thread.get("thread_key", "")) != normalized_thread_key
            and all(str(item.get("thread_key", "")) == normalized_thread_key for item in list(temporal.get("items", []))),
            "expired_items_ignored": not any(
                str(item.get("dedupe_key", "")) == f"stage20-expired:{run_id}" and bool(item.get("present", False))
                for item in list(temporal.get("items", []))
            )
            and bool(expired.get("expired", False) or expired.get("status") == "expired"),
            "explicit_memory_query_still_escalates": str(explicit_packet.get("recall_reason", "")).startswith("stage17:")
            and str(explicit_packet.get("tier", "")) in {"recall", "deep_recall"},
            "fulfilled_resume_not_reused": not any(
                str(item.get("dedupe_key", "")) == f"stage20-resume:{run_id}"
                for item in list(dict(fulfilled_packet.get("stage20", {})).get("resume_candidates", []))
            ),
            "canonical_wechat_identity_preserved": normalized_thread_key.startswith("wechat:")
            and str(packet.get("stage20", {}).get("thread_key", "")).startswith("wechat:"),
            "stage19_acceptance_green": str(stage19_report.get("status", "")).strip() == "pass",
        }
        return {
            "status": "pass" if all(checks.values()) else "fail",
            "stage": "temporal-commitments-and-interruption-recovery-stage20",
            "checks": checks,
            "thread_key": normalized_thread_key,
            "chat_name": normalized_chat_name,
            "channel": normalized_channel,
            "deferred_job_id": deferred_job_id,
            "duplicate_job_id": duplicate_job_id,
            "due_resume": due_resume,
            "open_loops": open_loops,
            "commitments": commitments,
            "resume_trace": resume_trace,
            "packet_stage20": dict(packet.get("stage20", {})),
            "explicit_memory_probe": {
                "tier": explicit_packet.get("tier"),
                "recall_reason": explicit_packet.get("recall_reason"),
                "memory_route": explicit_packet.get("memory_route"),
            },
            "close_report": close_report,
            "cleanup_report": cleanup_report,
            "fulfilled_stage20": dict(fulfilled_packet.get("stage20", {})),
            "stage19": {"status": stage19_report.get("status"), "checks": stage19_report.get("checks", {})},
        }

    def _accept_stage21_impl(
        self,
        *,
        thread_key: str | None = None,
        chat_name: str | None = None,
        channel: str = "wechat",
        sender: str | None = None,
        artifact_dir: str | None = None,
    ) -> dict[str, Any]:
        normalized_channel = str(channel or "wechat").strip() or "wechat"
        requested_chat_name = str(chat_name or "TestUser").strip()
        requested_thread_key = str(thread_key or requested_chat_name).strip()
        if normalized_channel == "wechat" and requested_thread_key and not (
            requested_thread_key.startswith("wechat:")
            or requested_thread_key.startswith("wxid_")
            or requested_thread_key.endswith("@chatroom")
        ):
            requested_thread_key = f"wechat:{requested_thread_key}"
        run_id = stable_digest(requested_thread_key, requested_chat_name, utc_now())[:12]
        probe_chat_name = f"{requested_chat_name}-stage21-{run_id}"
        probe_thread_key = f"wechat:{probe_chat_name}" if normalized_channel == "wechat" else f"{requested_thread_key}:{run_id}"
        query = "continue this carefully"
        context = {
            "channel": normalized_channel,
            "thread_key": probe_thread_key,
            "chat_name": probe_chat_name,
            "sender": str(sender or requested_chat_name),
            "attachments": [],
        }

        fixture_dir = self.config.runtime.repo_root / "tests" / "fixtures" / "stage14"
        with tempfile.TemporaryDirectory(prefix="holo-stage21-accept-") as temp_dir:
            artifact_root = Path(artifact_dir).resolve() if str(artifact_dir or "").strip() else Path(temp_dir)
            replay_before = self.memory.replay_policy_regret(
                source_type="synthetic_fixture",
                fixture_path=str(fixture_dir),
                channel=normalized_channel,
                limit=4,
                artifact_dir=str(artifact_root / "replay-before"),
            )

            for index in range(6):
                self.memory.appraise_outcome(
                    channel=normalized_channel,
                    thread_key=probe_thread_key,
                    chat_name=probe_chat_name,
                    action_type="defer_reply",
                    action_ref=f"accept-stage21-good-defer-{run_id}-{index}",
                    was_rewarding=0.86,
                    was_ignored=0.02,
                    relational_delta=0.11,
                    identity_delta=0.12,
                    future_initiative_bias=0.48,
                    future_resistance_bias=0.05,
                    metadata={
                        "predicted_outcome": {
                            "predicted_relational_delta": 0.1,
                            "predicted_identity_delta": 0.11,
                            "predicted_response_quality": 0.84,
                            "predicted_risk": 0.08,
                        },
                        "reply_latency_seconds": 90.0,
                        "initiative_success": 1.0,
                        "correction_count": 0,
                        "query": query,
                        "evidence_refs": [f"accept-stage21:good-defer:{run_id}:{index}"],
                    },
                )
                self.memory.appraise_outcome(
                    channel=normalized_channel,
                    thread_key=probe_thread_key,
                    chat_name=probe_chat_name,
                    action_type="counter_offer",
                    action_ref=f"accept-stage21-reject-counter-{run_id}-{index}",
                    was_rewarding=0.76,
                    was_ignored=0.04,
                    relational_delta=0.08,
                    identity_delta=0.14,
                    future_initiative_bias=0.32,
                    future_resistance_bias=0.08,
                    metadata={
                        "predicted_outcome": {
                            "predicted_relational_delta": 0.08,
                            "predicted_identity_delta": 0.13,
                            "predicted_response_quality": 0.74,
                            "predicted_risk": 0.1,
                        },
                        "reply_latency_seconds": 120.0,
                        "initiative_success": 1.0,
                        "correction_count": 0,
                        "query": query,
                        "evidence_refs": [f"accept-stage21:reject-counter:{run_id}:{index}"],
                    },
                )

            self.memory.clear_packet_cache()
            before_packet = self.memory.sidecar_packet(query, context={**context, "message_id": f"accept-stage21-before-{run_id}", "event_id": "2101"})
            candidates = self.show_policy_candidates(thread_key=probe_thread_key, chat_name=probe_chat_name, channel=normalized_channel)
            defer_candidate = next((dict(item) for item in candidates.get("candidates", []) if str(item.get("action_type", "")) == "defer_reply"), {})
            reject_candidate = next((dict(item) for item in candidates.get("candidates", []) if str(item.get("action_type", "")) == "counter_offer"), {})
            approved = self.memory.graph.review_policy_candidate(
                policy_id=str(defer_candidate.get("policy_id", "") or ""),
                approved=True,
                replay_report=replay_before,
                reason="accept_stage21_replay_approval",
            )
            rejected = self.memory.graph.review_policy_candidate(
                policy_id=str(reject_candidate.get("policy_id", "") or ""),
                approved=False,
                replay_report=replay_before,
                reason="accept_stage21_replay_rejection",
            )
            self.memory.clear_packet_cache()
            after_packet = self.memory.sidecar_packet(query, context={**context, "message_id": f"accept-stage21-after-{run_id}", "event_id": "2102"})
            influence = self.trace_policy_influence(thread_key=probe_thread_key, chat_name=probe_chat_name, channel=normalized_channel, query=query)
            replay_after = self.memory.replay_policy_regret(
                source_type="synthetic_fixture",
                fixture_path=str(fixture_dir),
                channel=normalized_channel,
                limit=4,
                artifact_dir=str(artifact_root / "replay-after"),
            )
            rollback = self.rollback_policy(policy_id=str(approved.get("policy_id", "") or approved.get("id", "")), reason="accept_stage21_rollback_probe")
            self.memory.clear_packet_cache()
            rollback_packet = self.memory.sidecar_packet(query, context={**context, "message_id": f"accept-stage21-rollback-{run_id}", "event_id": "2103"})

        stage20_report = self.accept_stage20(
            thread_key=requested_thread_key,
            chat_name=requested_chat_name,
            channel=normalized_channel,
            sender=sender,
            artifact_dir=artifact_dir,
        )

        def _action_row(packet: dict[str, Any], action_type: str) -> dict[str, Any]:
            return next((dict(item) for item in list(packet.get("action_market", [])) if str(item.get("action_type", "")) == action_type), {})

        before_defer = _action_row(before_packet, "defer_reply")
        after_defer = _action_row(after_packet, "defer_reply")
        rollback_defer = _action_row(rollback_packet, "defer_reply")
        before_regret = float(dict(replay_before.get("raw_aggregate_metrics", replay_before.get("aggregate_metrics", {}))).get("policy_regret_vs_best_available_action", 0.0) or 0.0)
        after_regret = float(dict(replay_after.get("raw_aggregate_metrics", replay_after.get("aggregate_metrics", {}))).get("policy_regret_vs_best_available_action", 0.0) or 0.0)
        hard_policy_decision = self.policy.outbound_decision(
            incoming_text="accept stage21 hard gate",
            reply_text="",
            recent_outbound_count=0,
            is_existing_thread=True,
            is_proactive=False,
            channel=normalized_channel,
        )
        checks = {
            "policy_candidate_created_from_repeated_evidence": bool(defer_candidate)
            and int(defer_candidate.get("support_count", 0) or 0) >= 3,
            "replay_can_approve_candidate": str(approved.get("status", "")) == "promoted"
            and str(approved.get("replay_approval_status", "")) == "approved",
            "replay_can_reject_candidate": str(rejected.get("status", "")) == "rejected"
            and str(rejected.get("replay_approval_status", "")) == "rejected",
            "promoted_policy_changes_ranking_fixture": float(after_defer.get("score", 0.0) or 0.0) > float(before_defer.get("score", 0.0) or 0.0)
            and float(after_defer.get("policy_sedimentation_delta", 0.0) or 0.0) > 0.0,
            "rollback_restores_old_behavior": str(rollback.get("status", "")) == "rolled_back"
            and abs(float(rollback_defer.get("policy_sedimentation_delta", 0.0) or 0.0)) == 0.0,
            "policy_regret_not_worse": after_regret <= before_regret + 0.001,
            "canonical_wechat_identity_preserved": normalized_channel != "wechat" or probe_thread_key.startswith("wechat:"),
            "hard_policy_gate_preserved": not bool(hard_policy_decision.allowed),
            "stage20_acceptance_green": str(stage20_report.get("status", "")) == "pass",
        }
        return {
            "status": "pass" if all(checks.values()) else "fail",
            "stage": "policy-sedimentation-and-negotiated-will-stage21",
            "checks": checks,
            "thread_key": requested_thread_key,
            "chat_name": requested_chat_name,
            "channel": normalized_channel,
            "probe_thread_key": probe_thread_key,
            "candidate": defer_candidate,
            "approved_policy": approved,
            "rejected_policy": rejected,
            "before_stage21": dict(before_packet.get("stage21", {})),
            "after_stage21": dict(after_packet.get("stage21", {})),
            "rollback_stage21": dict(rollback_packet.get("stage21", {})),
            "policy_influence": influence,
            "rollback": rollback,
            "replay_regret": {"before": before_regret, "after": after_regret},
            "stage20": {"status": stage20_report.get("status"), "checks": stage20_report.get("checks", {})},
        }

    def _accept_stage22_impl(
        self,
        *,
        thread_key: str | None = None,
        chat_name: str | None = None,
        channel: str = "wechat",
        sender: str | None = None,
        artifact_dir: str | None = None,
    ) -> dict[str, Any]:
        normalized_channel = str(channel or "wechat").strip() or "wechat"
        requested_chat_name = str(chat_name or "TestUser").strip()
        requested_thread_key = str(thread_key or requested_chat_name).strip()
        if normalized_channel == "wechat":
            requested_thread_key = self._stage22_normalize_wechat_thread(requested_thread_key, requested_chat_name)
        run_id = stable_digest(requested_thread_key, requested_chat_name, utc_now())[:12]
        probe_chat_name = f"{requested_chat_name}-stage22-{run_id}"
        probe_thread_key = f"wechat:{probe_chat_name}" if normalized_channel == "wechat" else f"{requested_thread_key}:{run_id}"
        original_mode = getattr(self.config.autonomy, "stage22_canary_mode", "shadow")
        original_whitelist = tuple(getattr(self.config.autonomy, "stage22_canary_whitelist_threads", ()))
        original_artifact_root = getattr(self.config.autonomy, "stage22_canary_artifact_root", "artifacts/canary/stage22")
        original_capture = bool(getattr(self.config.autonomy, "stage22_canary_artifact_capture", True))
        original_rate_thread = int(getattr(self.config.autonomy, "stage22_canary_max_replies_per_thread_per_hour", 12) or 12)
        original_rate_global = int(getattr(self.config.autonomy, "stage22_canary_max_replies_global_per_hour", 30) or 30)
        artifact_root = Path(artifact_dir).resolve() / "stage22-canary" if str(artifact_dir or "").strip() else self._stage22_artifact_root()
        self.set_canary_rollback(enabled=False, reason="accept_stage22_start")
        try:
            self.config.autonomy.stage22_canary_mode = "shadow"
            self.config.autonomy.stage22_canary_whitelist_threads = (probe_thread_key,)
            self.config.autonomy.stage22_canary_artifact_capture = True
            self.config.autonomy.stage22_canary_artifact_root = str(artifact_root)
            shadow_result = self.handle_reply(
                {
                    "chat_name": probe_chat_name,
                    "thread_key": probe_thread_key,
                    "channel": normalized_channel,
                    "sender": str(sender or requested_chat_name),
                    "text": "later after lunch",
                    "message_id": f"accept-stage22-shadow-{run_id}",
                }
            )
            shadow_trace_id = int(dict(shadow_result.get("stage22", {})).get("trace_id", 0) or 0)
            trace_rows = self.store.list_canary_traces(channel=normalized_channel, thread_key=probe_thread_key, limit=8)
            latest_trace = trace_rows[0] if trace_rows else {}
            artifact_path = str(dict(shadow_result.get("stage22", {})).get("artifact_path", "") or latest_trace.get("artifact_path", ""))

            self.config.autonomy.stage22_canary_mode = "canary_live"
            self.config.autonomy.stage22_canary_whitelist_threads = (probe_thread_key,)
            self.config.autonomy.stage22_canary_max_replies_per_thread_per_hour = max(1, original_rate_thread)
            self.config.autonomy.stage22_canary_max_replies_global_per_hour = max(1, original_rate_global)
            live_clear_trace = self.trace_canary_decision(
                thread_key=probe_thread_key,
                chat_name=probe_chat_name,
                channel=normalized_channel,
                query="stage22 live gate clear",
            )
            rollback_on = self.set_canary_rollback(enabled=True, reason="accept_stage22_probe")
            rollback_trace = self.trace_canary_decision(
                thread_key=probe_thread_key,
                chat_name=probe_chat_name,
                channel=normalized_channel,
                query="stage22 live gate rollback",
            )
            rollback_off = self.set_canary_rollback(enabled=False, reason="accept_stage22_probe_done")
            self.config.autonomy.stage22_canary_max_replies_per_thread_per_hour = 0
            rate_trace = self.trace_canary_decision(
                thread_key=probe_thread_key,
                chat_name=probe_chat_name,
                channel=normalized_channel,
                query="stage22 live gate rate limit",
            )
            self.config.autonomy.stage22_canary_max_replies_per_thread_per_hour = max(1, original_rate_thread)

            world_signal = self.memory.record_world_coupling_signal(
                channel=normalized_channel,
                thread_key=probe_thread_key,
                chat_name=probe_chat_name,
                cue_type="task_cue",
                summary="stage22 acceptance has a bounded live canary cue",
                source_ref=f"accept-stage22:{run_id}",
                confidence=0.74,
                evidence_refs=[f"accept_stage22:{run_id}:world_cue"],
                metadata={"source": "accept_stage22"},
            )
            self.memory.clear_packet_cache()
            packet = self.memory.sidecar_packet(
                "still here?",
                context={
                    "channel": normalized_channel,
                    "thread_key": probe_thread_key,
                    "chat_name": probe_chat_name,
                    "sender": str(sender or requested_chat_name),
                    "attachments": [],
                    "message_id": f"accept-stage22-world-{run_id}",
                    "event_id": "2201",
                },
            )
            world_coupling = self.show_world_coupling(
                thread_key=probe_thread_key,
                chat_name=probe_chat_name,
                channel=normalized_channel,
                limit=6,
            )
            metrics = self.show_blackbox_metrics(window_hours=24.0, channel=normalized_channel, thread_key=probe_thread_key, limit=100)
            online = self.show_online_canary(limit=12)
            replay = self.replay_live_artifacts(since_hours=24.0, limit=8, artifact_dir=str(Path(artifact_dir).resolve() / "stage22-live-replay") if str(artifact_dir or "").strip() else None)
            stage21_report = self.accept_stage21(
                thread_key=requested_thread_key,
                chat_name=requested_chat_name,
                channel=normalized_channel,
                sender=sender,
                artifact_dir=artifact_dir,
            )
        finally:
            self.set_canary_rollback(enabled=False, reason="accept_stage22_cleanup")
            self.config.autonomy.stage22_canary_mode = original_mode
            self.config.autonomy.stage22_canary_whitelist_threads = original_whitelist
            self.config.autonomy.stage22_canary_artifact_root = original_artifact_root
            self.config.autonomy.stage22_canary_artifact_capture = original_capture
            self.config.autonomy.stage22_canary_max_replies_per_thread_per_hour = original_rate_thread
            self.config.autonomy.stage22_canary_max_replies_global_per_hour = original_rate_global

        live_gate = dict(live_clear_trace.get("gate", {}))
        rollback_gate = dict(rollback_trace.get("gate", {}))
        rate_gate = dict(rate_trace.get("gate", {}))
        stage22_packet = dict(packet.get("stage22", {}))
        metric_keys = {
            "reflex_hit_rate",
            "reread_history_rate",
            "clarification_thrash_rate",
            "duplicate_followup_rate",
            "resume_success_after_interruption",
            "latency_buckets_by_action_type",
        }
        checks = {
            "shadow_mode_captures_and_suppresses_send": bool(shadow_result.get("stage22_shadow", False))
            and self._stage23_is_delivery_capable_action(str(shadow_result.get("action", "")))
            and str(shadow_result.get("semantic_action", "")) == str(shadow_result.get("action", ""))
            and str(shadow_result.get("returned_action", "")) == "silence"
            and bool(shadow_result.get("delivery_suppressed_by_canary", False))
            and str(dict(shadow_result.get("stage22", {})).get("mode", "")) == "shadow"
            and shadow_trace_id > 0,
            "artifact_capture_by_default": bool(artifact_path) and Path(artifact_path).exists(),
            "canary_live_requires_gates": bool(live_gate.get("allowed", False))
            and str(live_gate.get("mode", "")) == "canary_live"
            and bool(live_gate.get("whitelisted", False)),
            "rollback_switch_reversible": bool(rollback_on.get("rollback_enabled", False))
            and str(rollback_gate.get("verdict", "")) == "rollback_enabled"
            and not bool(rollback_off.get("rollback_enabled", True)),
            "rate_limit_blocks_without_selecting_new_action": str(rate_gate.get("verdict", "")) == "thread_rate_limited"
            and bool(str(rate_gate.get("selected_action", "")).strip()),
            "metrics_are_deterministic_and_visible": metric_keys.issubset(set(metrics.keys()))
            and int(metrics.get("total_traces", 0) or 0) >= 1,
            "live_artifacts_feed_stage14_replay": int(replay.get("fixture_count", 0) or 0) >= 1
            and str(replay.get("status", "")) in {"pass", "warn"},
            "world_coupling_hydrates_without_heavy_recall": bool(world_signal.get("present", False))
            and bool(stage22_packet.get("world_coupling_visible", False))
            and bool(stage22_packet.get("world_coupling_used_for_thread", False))
            and str(packet.get("tier", "")) not in {"deep_recall"},
            "canonical_wechat_identity_preserved": normalized_channel != "wechat" or probe_thread_key.startswith("wechat:"),
            "stage21_acceptance_green": str(stage21_report.get("status", "")) == "pass",
        }
        return {
            "status": "pass" if all(checks.values()) else "fail",
            "stage": "bounded-blackbox-online-canary-stage22",
            "checks": checks,
            "thread_key": requested_thread_key,
            "chat_name": requested_chat_name,
            "channel": normalized_channel,
            "probe_thread_key": probe_thread_key,
            "shadow_result": shadow_result,
            "online_canary": online,
            "metrics": metrics,
            "live_gate": live_gate,
            "rollback_gate": rollback_gate,
            "rate_gate": rate_gate,
            "world_coupling": world_coupling,
            "packet_stage22": stage22_packet,
            "replay_live_artifacts": {
                "status": replay.get("status"),
                "fixture_count": replay.get("fixture_count"),
                "fixture_dir": replay.get("fixture_dir"),
            },
            "stage21": {"status": stage21_report.get("status"), "checks": stage21_report.get("checks", {})},
        }

    def _accept_stage23_impl(
        self,
        *,
        thread_key: str | None = None,
        chat_name: str | None = None,
        channel: str = "wechat",
        sender: str | None = None,
        artifact_dir: str | None = None,
    ) -> dict[str, Any]:
        normalized_channel = str(channel or "wechat").strip() or "wechat"
        requested_chat_name = str(chat_name or "TestUser").strip()
        requested_thread_key = str(thread_key or requested_chat_name).strip()
        if normalized_channel == "wechat":
            requested_thread_key = self._stage22_normalize_wechat_thread(requested_thread_key, requested_chat_name)
        run_id = stable_digest(requested_thread_key, requested_chat_name, utc_now(), "stage23")[:12]
        probe_chat_name = f"{requested_chat_name}-stage23-{run_id}"
        probe_thread_key = f"wechat:{probe_chat_name}" if normalized_channel == "wechat" else f"{requested_thread_key}:{run_id}"
        original_mode = getattr(self.config.autonomy, "stage22_canary_mode", "shadow")
        original_whitelist = tuple(getattr(self.config.autonomy, "stage22_canary_whitelist_threads", ()))
        stage22_report = self.accept_stage22(
            thread_key=requested_thread_key,
            chat_name=requested_chat_name,
            channel=normalized_channel,
            sender=sender,
            artifact_dir=artifact_dir,
        )
        fixture_dir = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "stage14"
        replay_root = Path(artifact_dir).resolve() / "stage23-replay" if str(artifact_dir or "").strip() else None
        self.set_canary_rollback(enabled=False, reason="accept_stage23_start")
        try:
            self.config.autonomy.stage22_canary_mode = "shadow"
            self.config.autonomy.stage22_canary_whitelist_threads = (probe_thread_key,)
            shadow_probe = self.handle_reply(
                {
                    "chat_name": probe_chat_name,
                    "thread_key": probe_thread_key,
                    "channel": normalized_channel,
                    "sender": str(sender or requested_chat_name),
                    "text": "later after lunch",
                    "message_id": f"accept-stage23-shadow-{run_id}",
                }
            )
            replay_report = self.replay_policy_regret(
                source_type="synthetic_fixture",
                fixture_path=str(fixture_dir),
                channel="wechat",
                limit=8,
                artifact_dir=str(replay_root) if replay_root is not None else None,
            )
        finally:
            self.set_canary_rollback(enabled=False, reason="accept_stage23_cleanup")
            self.config.autonomy.stage22_canary_mode = original_mode
            self.config.autonomy.stage22_canary_whitelist_threads = original_whitelist

        aggregate = dict(replay_report.get("aggregate_metrics", {}))
        raw = dict(replay_report.get("raw_aggregate_metrics", {}))
        checks = {
            "stage22_acceptance_green": str(stage22_report.get("status", "")) == "pass",
            "shadow_preserves_semantic_action": str(shadow_probe.get("action", "")) == "defer_reply"
            and str(shadow_probe.get("semantic_action", "")) == "defer_reply"
            and str(shadow_probe.get("returned_action", "")) == "silence"
            and not bool(shadow_probe.get("delivery_send_allowed", True))
            and bool(shadow_probe.get("delivery_suppressed_by_canary", False))
            and not bool(shadow_probe.get("job_id")),
            "shadow_trace_preserves_stage22_shell": str(dict(shadow_probe.get("stage22", {})).get("mode", "")) == "shadow"
            and str(dict(shadow_probe.get("stage22", {})).get("verdict", "")) == "shadow_suppressed",
            "raw_replay_metrics_visible": {"risk_mae", "policy_regret_vs_best_available_action"}.issubset(set(raw.keys())),
            "display_replay_metrics_visible": {"risk_mae", "policy_regret_vs_best_available_action"}.issubset(set(aggregate.keys())),
            "raw_and_display_replay_are_consistent": self._stage14_display_matches_raw(aggregate, raw, "risk_mae")
            and self._stage14_display_matches_raw(aggregate, raw, "policy_regret_vs_best_available_action"),
        }
        return {
            "status": "pass" if all(checks.values()) else "fail",
            "stage": "kernel-shell-orthogonalization-and-release-parity-stage23",
            "checks": checks,
            "thread_key": requested_thread_key,
            "chat_name": requested_chat_name,
            "channel": normalized_channel,
            "probe_thread_key": probe_thread_key,
            "shadow_probe": shadow_probe,
            "stage22": {"status": stage22_report.get("status"), "checks": stage22_report.get("checks", {})},
            "replay": {
                "status": replay_report.get("status"),
                "fixture_count": replay_report.get("fixture_count"),
                "aggregate_metrics": aggregate,
                "raw_aggregate_metrics": raw,
                "artifact_dir": dict(replay_report.get("artifacts", {})).get("artifact_dir", ""),
            },
        }

    def _accept_stage24_impl(
        self,
        *,
        thread_key: str | None = None,
        chat_name: str | None = None,
        channel: str = "wechat",
        sender: str | None = None,
        artifact_dir: str | None = None,
    ) -> dict[str, Any]:
        normalized_channel = str(channel or "wechat").strip() or "wechat"
        requested_chat_name = str(chat_name or "TestUser").strip()
        requested_thread_key = str(thread_key or requested_chat_name).strip()
        if normalized_channel == "wechat":
            requested_thread_key = self._stage22_normalize_wechat_thread(requested_thread_key, requested_chat_name)
        stage23_report = self.accept_stage23(
            thread_key=requested_thread_key,
            chat_name=requested_chat_name,
            channel=normalized_channel,
            sender=sender,
            artifact_dir=artifact_dir,
        )
        run_id = stable_digest(requested_thread_key, requested_chat_name, utc_now(), "stage24")[:12]
        probe_chat_name = f"{requested_chat_name}-stage24-{run_id}"
        probe_thread_key = f"wechat:{probe_chat_name}" if normalized_channel == "wechat" else f"{requested_thread_key}:{run_id}"
        probe_turn = ChatTurn(
            chat_name=probe_chat_name,
            text="lunch tomorrow?",
            sender=str(sender or requested_chat_name),
            channel=normalized_channel,
            thread_key=probe_thread_key,
            message_id=f"accept-stage24-inbound-{run_id}",
            metadata={},
        )
        incoming = probe_turn.to_incoming_message()
        inbound_state = self._update_active_thread_state(
            turn=probe_turn,
            incoming=incoming,
            direction="inbound",
            event_row_id=2401,
            text=probe_turn.text,
            metadata={"source": "accept-stage24", "_stage24_force_scene_hint": True},
        )
        context = {
            "channel": normalized_channel,
            "thread_key": probe_thread_key,
            "incoming_thread_key": probe_thread_key,
            "message_id": incoming.message_id,
            "chat_name": probe_chat_name,
            "sender": str(sender or requested_chat_name),
            "recent_history": [
                {"direction": "inbound", "body_text": "old line one"},
                {"direction": "outbound", "body_text": "old line two"},
                {"direction": "inbound", "body_text": "old line three"},
            ],
            "attachments": [],
            "active_thread_state": inbound_state,
            "event_id": "2401",
        }
        fast_packet = self.memory.sidecar_packet(probe_turn.text, context=context)
        fast_turn_context = TurnContext(
            channel=normalized_channel,
            thread_key=probe_thread_key,
            chat_name=probe_chat_name,
            sender=str(sender or requested_chat_name),
            user_text=probe_turn.text,
            sidecar=fast_packet,
            mind_packet=fast_packet,
            attention_state=build_attention_state(probe_turn.text, channel=normalized_channel, metadata={}),
            emotion_state=dict(fast_packet.get("state", {}).get("emotion_state", {})),
            history=list(context["recent_history"]),
            metadata={},
            capability_context={},
        )
        fast_turn_plan = build_turn_plan(fast_turn_context, self.config)
        fast_prompt = render_chat_prompt(fast_turn_context, turn_plan=fast_turn_plan)
        scene_diag = self.show_scene_state(thread_key=probe_thread_key, chat_name=probe_chat_name, channel=normalized_channel)
        branch_trace = self.trace_predicted_branches(thread_key=probe_thread_key, chat_name=probe_chat_name, channel=normalized_channel)
        compression_trace = self.trace_scene_compression(thread_key=probe_thread_key, chat_name=probe_chat_name, channel=normalized_channel)
        outbound_state = self._update_active_thread_state(
            turn=probe_turn,
            incoming=incoming,
            direction="outbound",
            event_row_id=2402,
            text="later after lunch works, we can keep tomorrow in view",
            action_type="reply_once",
            selected_action={"action_type": "reply_once", "score": 0.72},
            metadata={"source": "accept-stage24"},
        )
        reloaded_state = self.memory.active_thread_state(channel=normalized_channel, thread_key=probe_thread_key, chat_name=probe_chat_name)
        recall_packet = self.memory.sidecar_packet(
            "remember previous history",
            context={**context, "message_id": f"accept-stage24-recall-{run_id}", "active_thread_state": inbound_state, "event_id": "2403"},
        )
        action_market = self.memory.action_market(
            thread_key=probe_thread_key,
            chat_name=probe_chat_name,
            channel=normalized_channel,
            query=probe_turn.text,
            limit=6,
        )
        scene_state = dict(reloaded_state.get("scene_state", {}))
        checks = {
            "stage23_acceptance_green": str(stage23_report.get("status", "")) == "pass",
            "scene_fields_visible": all(
                key in scene_state
                for key in (
                    "shared_frame",
                    "topic_stack",
                    "salient_objects",
                    "latent_questions",
                    "predicted_branches",
                    "relationship_trajectory",
                    "response_sketch",
                    "scene_confidence",
                    "freshness_at",
                )
            ),
            "scene_state_persisted": bool(scene_state.get("freshness_at")) and bool(reloaded_state.get("present", False)),
            "ordinary_short_turn_uses_scene_before_history": "scene_state:" in fast_prompt
            and "scene_next:" in fast_prompt
            and "old line two" not in fast_prompt
            and int(fast_turn_context.metadata.get("history_lines_in_prompt", 0) or 0) <= 1,
            "explicit_memory_query_still_escalates": str(recall_packet.get("tier", "")).strip() in {"recall", "deep_recall"}
            and str(recall_packet.get("recall_reason", "")).startswith("stage17:"),
            "action_market_scene_overlay_visible": bool(action_market.get("action_market"))
            and all("scene_delta" in item and "scene_rationale" in item for item in action_market.get("action_market", [])),
            "scene_diagnostics_visible": bool(scene_diag.get("scene_state")) and "compression_mode" in compression_trace,
            "outbound_scene_updates_state": bool(dict(outbound_state.get("scene_state", {})).get("response_sketch", "") or scene_state.get("response_sketch", "")),
        }
        return {
            "status": "pass" if all(checks.values()) else "fail",
            "stage": "scene-state-continuity-layer-stage24",
            "checks": checks,
            "thread_key": requested_thread_key,
            "chat_name": requested_chat_name,
            "channel": normalized_channel,
            "probe_thread_key": probe_thread_key,
            "stage23": {"status": stage23_report.get("status"), "checks": stage23_report.get("checks", {})},
            "scene_state": scene_diag,
            "predicted_branches": branch_trace,
            "scene_compression": compression_trace,
            "fast_packet": {
                "tier": fast_packet.get("tier"),
                "memory_route": fast_packet.get("memory_route"),
                "stage24": dict(fast_packet.get("stage24", {})),
                "history_lines_in_prompt": int(fast_turn_context.metadata.get("history_lines_in_prompt", 0) or 0),
                "scene_lines_in_prompt": int(fast_turn_context.metadata.get("scene_lines_in_prompt", 0) or 0),
                "prompt_excerpt": compact_text(fast_prompt, 360),
            },
            "recall_probe": {
                "tier": recall_packet.get("tier"),
                "recall_reason": recall_packet.get("recall_reason"),
                "memory_route": recall_packet.get("memory_route"),
            },
            "action_market": action_market,
            "reloaded_state": reloaded_state,
        }

    def _accept_stage25_impl(
        self,
        *,
        thread_key: str | None = None,
        chat_name: str | None = None,
        channel: str = "wechat",
        sender: str | None = None,
        artifact_dir: str | None = None,
    ) -> dict[str, Any]:
        normalized_channel = str(channel or "wechat").strip() or "wechat"
        requested_chat_name = str(chat_name or "TestUser").strip()
        requested_thread_key = str(thread_key or requested_chat_name).strip()
        if normalized_channel == "wechat":
            requested_thread_key = self._stage22_normalize_wechat_thread(requested_thread_key, requested_chat_name)
        stage24_report = self.accept_stage24(
            thread_key=requested_thread_key,
            chat_name=requested_chat_name,
            channel=normalized_channel,
            sender=sender,
            artifact_dir=artifact_dir,
        )
        run_id = stable_digest(requested_thread_key, requested_chat_name, utc_now(), "stage25")[:12]
        probe_chat_name = f"{requested_chat_name}-stage25-{run_id}"
        probe_thread_key = f"wechat:{probe_chat_name}" if normalized_channel == "wechat" else f"{requested_thread_key}:{run_id}"
        probe_text = "still here?"
        self.memory.rag.archive_turn(
            "stage25 dense continuity seed",
            "stage25 should keep this hot thread warm between turns without deeper recall",
            source="accept_stage25.seed",
            tags=["wechat", "stage25"],
            turn_id=f"accept-stage25-{run_id}",
            metadata={"channel": normalized_channel, "thread_key": probe_thread_key, "chat_name": probe_chat_name},
        )
        sync_report = self.memory.graph.sync_thread(channel=normalized_channel, thread_key=probe_thread_key, chat_name=probe_chat_name)
        inspect = self.memory.graph.inspect_graph(thread_key=probe_thread_key, chat_name=probe_chat_name, channel=normalized_channel, limit=6)
        archive_node = next((dict(node) for node in inspect.get("nodes", []) if str(node.get("source_store", "")) == "archive"), {})
        inbound_state = self.memory.update_active_thread_state(
            channel=normalized_channel,
            thread_key=probe_thread_key,
            chat_name=probe_chat_name,
            direction="inbound",
            text="we can keep the thread warm for a little while",
            message_id=f"accept-stage25-inbound-{run_id}",
            event_row_id=2501,
            metadata={"source": "accept-stage25", "_stage24_force_scene_hint": True},
        )
        stream_reports = [
            self.memory.record_stream_run(
                stream_name,
                status="ok",
                note="stage25_acceptance",
                payload={
                    "thoughts": [
                        {
                            "channel": normalized_channel,
                            "thread_key": probe_thread_key,
                            "chat_name": probe_chat_name,
                            "motif": f"stage25_{stream_name}",
                            "source_archive_id": str(archive_node.get("source_id", archive_node.get("id", "")) or ""),
                        }
                    ],
                    "selected_memory_ids": [str(archive_node.get("source_id", archive_node.get("id", "")) or "")],
                },
            )
            for stream_name in ("association_stream", "social_stream")
        ]
        dense_before = self.show_dense_working_set(channel=normalized_channel)
        budget_diag = self.show_continuity_budget(channel=normalized_channel)
        pulse_trace = self.trace_thread_pulse(
            thread_key=probe_thread_key,
            chat_name=probe_chat_name,
            channel=normalized_channel,
            limit=8,
        )
        with self.memory.graph._lock:
            self.memory.graph.conn.execute(
                "UPDATE attention_frontier SET stale_after = ? WHERE channel = ? AND canonical_thread_key = ?",
                ("2000-01-01T00:00:00Z", normalized_channel, probe_thread_key),
            )
            self.memory.graph.conn.execute(
                "DELETE FROM active_thread_state WHERE channel = ? AND thread_key = ?",
                (normalized_channel, probe_thread_key),
            )
            self.memory.graph.conn.commit()
        warm_context = {
            "channel": normalized_channel,
            "thread_key": probe_thread_key,
            "incoming_thread_key": probe_thread_key,
            "message_id": f"accept-stage25-warm-{run_id}",
            "chat_name": probe_chat_name,
            "sender": str(sender or requested_chat_name),
            "attachments": [],
            "recent_history": [
                {"direction": "inbound", "body_text": "old line one"},
                {"direction": "outbound", "body_text": "old line two"},
                {"direction": "inbound", "body_text": "old line three"},
            ],
            "event_id": "2502",
        }
        warm_packet = self.memory.sidecar_packet(probe_text, context=warm_context)
        warm_turn_context = TurnContext(
            channel=normalized_channel,
            thread_key=probe_thread_key,
            chat_name=probe_chat_name,
            sender=str(sender or requested_chat_name),
            user_text=probe_text,
            sidecar=warm_packet,
            mind_packet=warm_packet,
            attention_state=build_attention_state(probe_text, channel=normalized_channel, metadata={}),
            emotion_state=dict(warm_packet.get("state", {}).get("emotion_state", {})),
            history=list(warm_context["recent_history"]),
            metadata={},
            capability_context={},
        )
        warm_turn_plan = build_turn_plan(warm_turn_context, self.config)
        warm_prompt = render_chat_prompt(warm_turn_context, turn_plan=warm_turn_plan)
        explicit_packet = self.memory.sidecar_packet(
            "remember previous history",
            context={**warm_context, "message_id": f"accept-stage25-recall-{run_id}", "event_id": "2503"},
        )
        reloaded_dense = {}
        reopened = MemoryBridge(
            self.config.runtime.repo_root,
            top_k=self.config.memory.prompt_top_k,
            graph_db_path=self.config.memory.mind_graph_db_path,
            stream_cadences=stream_cadences_from_config(self.config),
            graph_led_reply=self.config.memory.graph_led_reply,
            graph_fallback=self.config.memory.graph_fallback,
            deep_recall_on_memory_queries=self.config.memory.deep_recall_on_memory_queries,
            active_wechat_history_enabled=self.config.memory.active_wechat_history_enabled,
            vector_backend=self.config.memory.vector_backend,
            milvus_uri=self.config.memory.milvus_uri,
            milvus_collection_prefix=self.config.memory.milvus_collection_prefix,
            activation_cache_enabled=self.config.memory.activation_cache_enabled,
            private_memory_sync_enabled=self.config.memory.private_memory_sync_enabled,
            private_memory_repo_path=self.config.memory.private_memory_repo_path,
            stage25_max_hot_threads_per_cycle=self.config.memory.stage25_max_hot_threads_per_cycle,
            stage25_per_thread_pulse_budget=self.config.memory.stage25_per_thread_pulse_budget,
            stage25_skip_cold_without_pressure=self.config.memory.stage25_skip_cold_without_pressure,
            stage25_max_dense_working_set_threads=self.config.memory.stage25_max_dense_working_set_threads,
            stage25_cooldown_seconds_by_stream={
                "maintenance_stream": self.config.memory.stage25_maintenance_stream_cooldown_seconds,
                "association_stream": self.config.memory.stage25_association_stream_cooldown_seconds,
                "social_stream": self.config.memory.stage25_social_stream_cooldown_seconds,
                "deep_dream_cycle": self.config.memory.stage25_deep_dream_cycle_cooldown_seconds,
            },
            rag=self.memory.rag,
        )
        try:
            reloaded_dense = reopened.show_dense_working_set(channel=normalized_channel)
        finally:
            reopened.activation.close()
            reopened.graph.close()

        dense_entries = list(dict(dense_before.get("dense_working_set", {})).get("top_hot_threads", []))
        pulse_traces = list(pulse_trace.get("thread_pulse_trace", []))
        checks = {
            "stage24_acceptance_green": str(stage24_report.get("status", "")) == "pass",
            "allowed_streams_only": all(
                str(report.get("stream_name", "") or "") in {"maintenance_stream", "association_stream", "social_stream", "deep_dream_cycle"}
                for report in stream_reports
            ),
            "dense_working_set_persisted_and_bounded": bool(reloaded_dense.get("present", False))
            and int(reloaded_dense.get("entry_count", 0) or 0) <= int(self.config.memory.stage25_max_dense_working_set_threads)
            and any(str(item.get("thread_key", "") or "") == probe_thread_key for item in list(dict(reloaded_dense.get("dense_working_set", {})).get("top_hot_threads", []))),
            "pulse_trace_is_inspectable": bool(pulse_traces)
            and all(str(item.get("stream_name", "") or "") in {"maintenance_stream", "association_stream", "social_stream", "deep_dream_cycle"} for item in pulse_traces),
            "hot_thread_reenters_from_dense_before_deeper_recall": str(warm_packet.get("memory_route", "") or "") == "active_thread"
            and str(warm_packet.get("retrieval_mode", "") or "") == "active-thread-fast"
            and bool(dict(warm_packet.get("stage25", {})).get("working_set_used_for_thread", False))
            and not bool(dict(warm_packet.get("stage19", {})).get("frontier_used_for_thread", False)),
            "ordinary_turn_remains_history_light": int(warm_turn_context.metadata.get("history_lines_in_prompt", 0) or 0) <= 1
            and "old line two" not in warm_prompt,
            "explicit_memory_query_still_escalates": str(explicit_packet.get("tier", "")).strip() in {"recall", "deep_recall"}
            and str(explicit_packet.get("recall_reason", "")).startswith("stage17:"),
            "continuity_budget_visible": bool(budget_diag.get("configured_budget")) and bool(budget_diag.get("current_budget")),
            "dense_snapshot_shape_visible": all(
                key in dict(dense_before.get("dense_working_set", {}))
                for key in (
                    "top_hot_threads",
                    "current_self_pose",
                    "pending_interpersonal_pressure",
                    "open_loops_likely_to_reenter",
                    "budget",
                    "last_stream_name",
                    "updated_at",
                )
            ) and bool(dense_entries),
        }
        return {
            "status": "pass" if all(checks.values()) else "fail",
            "stage": "dense-continuity-scheduler-and-working-set-stage25",
            "checks": checks,
            "thread_key": requested_thread_key,
            "chat_name": requested_chat_name,
            "channel": normalized_channel,
            "probe_thread_key": probe_thread_key,
            "stage24": {"status": stage24_report.get("status"), "checks": stage24_report.get("checks", {})},
            "sync": sync_report,
            "stream_reports": stream_reports,
            "continuity_budget": budget_diag,
            "dense_working_set": dense_before,
            "thread_pulse": pulse_trace,
            "warm_packet": {
                "tier": warm_packet.get("tier"),
                "memory_route": warm_packet.get("memory_route"),
                "retrieval_mode": warm_packet.get("retrieval_mode"),
                "stage19": dict(warm_packet.get("stage19", {})),
                "stage24": dict(warm_packet.get("stage24", {})),
                "stage25": dict(warm_packet.get("stage25", {})),
                "history_lines_in_prompt": int(warm_turn_context.metadata.get("history_lines_in_prompt", 0) or 0),
                "prompt_excerpt": compact_text(warm_prompt, 360),
            },
            "explicit_recall_probe": {
                "tier": explicit_packet.get("tier"),
                "recall_reason": explicit_packet.get("recall_reason"),
                "memory_route": explicit_packet.get("memory_route"),
            },
            "reloaded_dense_working_set": reloaded_dense,
            "inbound_state": inbound_state,
        }

    def _accept_stage26_impl(
        self,
        *,
        thread_key: str | None = None,
        chat_name: str | None = None,
        channel: str = "wechat",
        sender: str | None = None,
        artifact_dir: str | None = None,
    ) -> dict[str, Any]:
        normalized_channel = str(channel or "wechat").strip() or "wechat"
        requested_chat_name = str(chat_name or "TestUser").strip()
        requested_thread_key = str(thread_key or requested_chat_name).strip()
        if normalized_channel == "wechat":
            requested_thread_key = self._stage22_normalize_wechat_thread(requested_thread_key, requested_chat_name)
        stage25_report = self.accept_stage25(
            thread_key=requested_thread_key,
            chat_name=requested_chat_name,
            channel=normalized_channel,
            sender=sender,
            artifact_dir=artifact_dir,
        )
        run_id = stable_digest(requested_thread_key, requested_chat_name, utc_now(), "stage26")[:12]
        probe_chat_name = f"{requested_chat_name}-stage26-{run_id}"
        probe_thread_key = f"wechat:{probe_chat_name}" if normalized_channel == "wechat" else f"{requested_thread_key}:{run_id}"
        other_chat_name = f"{probe_chat_name}-other"
        other_thread_key = f"wechat:{other_chat_name}" if normalized_channel == "wechat" else f"{requested_thread_key}:other:{run_id}"
        artifact_root = Path(artifact_dir).resolve() / "stage26-task-world" if str(artifact_dir or "").strip() else Path(tempfile.mkdtemp(prefix="holo-stage26-"))
        artifact_root.mkdir(parents=True, exist_ok=True)
        sample_file = artifact_root / "stage26-note.txt"
        atomic_write_text(sample_file, "deliver the thread-local task-world summary\n")
        sample_schedule = artifact_root / "stage26-schedule.txt"
        atomic_write_text(sample_schedule, "follow up tomorrow afternoon\n")

        file_artifact = self.memory.ingest_artifact(
            str(sample_file),
            note="thread-local file object for stage26",
            source="accept_stage26.file",
            tags=["stage26", "file"],
            dry_run=False,
            channel=normalized_channel,
            thread_key=probe_thread_key,
            chat_name=probe_chat_name,
            world_cue_type="file_artifact",
        )
        schedule_artifact = self.memory.ingest_artifact(
            str(sample_schedule),
            note="thread-local schedule object for stage26",
            source="accept_stage26.schedule",
            tags=["stage26", "schedule"],
            dry_run=False,
            channel=normalized_channel,
            thread_key=probe_thread_key,
            chat_name=probe_chat_name,
            world_cue_type="schedule_cue",
            due_at="2099-01-01T00:00:00Z",
        )
        task_object = self.memory.upsert_task_world_object(
            object_type="task",
            summary="send the stage26 task-world summary back into the same thread",
            thread_key=probe_thread_key,
            chat_name=probe_chat_name,
            channel=normalized_channel,
            source_ref="accept_stage26:task",
            confidence=0.76,
            metadata={"source": "accept_stage26", "family": "task"},
        )
        person_object = self.memory.upsert_task_world_object(
            object_type="person",
            summary="Mika is the external reviewer waiting for the same-thread update",
            thread_key=probe_thread_key,
            chat_name=probe_chat_name,
            channel=normalized_channel,
            source_ref="accept_stage26:person:Mika",
            confidence=0.72,
            metadata={"source": "accept_stage26", "family": "person"},
        )
        image_object = self.memory.upsert_task_world_object(
            object_type="image_summary",
            summary="screenshot summary shows the shared draft title and due date",
            thread_key=probe_thread_key,
            chat_name=probe_chat_name,
            channel=normalized_channel,
            source_ref="accept_stage26:image",
            confidence=0.7,
            metadata={"source": "accept_stage26", "family": "image_summary"},
        )
        commitment = self.memory.graph.upsert_temporal_item(
            item_type="commitment",
            channel=normalized_channel,
            thread_key=probe_thread_key,
            chat_name=probe_chat_name,
            confidence=0.74,
            source_event_id=f"accept-stage26-commitment-{run_id}",
            source_action_ref=f"stage26-task-{run_id}",
            source_action_type="defer_reply",
            due_at="2099-01-01T00:00:00Z",
            revisit_after="2099-01-01T00:00:00Z",
            resume_cue="send the promised task-world followup",
            dedupe_key=f"accept-stage26-commitment-{run_id}",
            status="scheduled",
            metadata={"source": "accept_stage26", "evidence_refs": [f"accept_stage26:{run_id}:commitment"]},
        )
        shared_task = self.memory.upsert_task_world_object(
            object_type="task",
            summary="shared deliverable visible in more than one thread",
            thread_key=probe_thread_key,
            chat_name=probe_chat_name,
            channel=normalized_channel,
            source_ref="accept_stage26:shared",
            confidence=0.69,
            linked_commitments=[str(commitment.get("dedupe_key", "") or "")],
            metadata={"source": "accept_stage26", "family": "shared_task"},
        )
        shared_task_other = self.memory.upsert_task_world_object(
            object_type="task",
            summary="shared deliverable visible in more than one thread",
            thread_key=other_thread_key,
            chat_name=other_chat_name,
            channel=normalized_channel,
            source_ref="accept_stage26:shared",
            confidence=0.69,
            metadata={"source": "accept_stage26", "family": "shared_task"},
        )

        task_world = self.show_task_world(
            thread_key=probe_thread_key,
            chat_name=probe_chat_name,
            channel=normalized_channel,
            limit=8,
            include_inactive=True,
        )
        object_trace = self.trace_world_object(object_id=str(shared_task.get("object_id", "") or str(task_object.get("object_id", "") or "")))
        link_trace = self.trace_thread_object_links(
            thread_key=probe_thread_key,
            chat_name=probe_chat_name,
            channel=normalized_channel,
            limit=8,
        )
        world_coupling = self.show_world_coupling(
            thread_key=probe_thread_key,
            chat_name=probe_chat_name,
            channel=normalized_channel,
            limit=8,
            include_inactive=True,
        )

        with self.memory.graph._lock:
            self.memory.graph.conn.execute(
                "UPDATE attention_frontier SET stale_after = ? WHERE channel = ? AND canonical_thread_key = ?",
                ("2000-01-01T00:00:00Z", normalized_channel, probe_thread_key),
            )
            self.memory.graph.conn.execute(
                "DELETE FROM active_thread_state WHERE channel = ? AND thread_key = ?",
                (normalized_channel, probe_thread_key),
            )
            self.memory.graph.conn.commit()
        self.memory.clear_packet_cache()
        warm_context = {
            "channel": normalized_channel,
            "thread_key": probe_thread_key,
            "incoming_thread_key": probe_thread_key,
            "message_id": f"accept-stage26-warm-{run_id}",
            "chat_name": probe_chat_name,
            "sender": str(sender or requested_chat_name),
            "attachments": [],
            "recent_history": [
                {"direction": "inbound", "body_text": "old line one"},
                {"direction": "outbound", "body_text": "old line two"},
                {"direction": "inbound", "body_text": "old line three"},
            ],
            "event_id": "2601",
        }
        warm_packet = self.memory.sidecar_packet("still here?", context=warm_context)
        warm_turn_context = TurnContext(
            channel=normalized_channel,
            thread_key=probe_thread_key,
            chat_name=probe_chat_name,
            sender=str(sender or requested_chat_name),
            user_text="still here?",
            sidecar=warm_packet,
            mind_packet=warm_packet,
            attention_state=build_attention_state("still here?", channel=normalized_channel, metadata={}),
            emotion_state=dict(warm_packet.get("state", {}).get("emotion_state", {})),
            history=list(warm_context["recent_history"]),
            metadata={},
            capability_context={},
        )
        warm_turn_plan = build_turn_plan(warm_turn_context, self.config)
        warm_prompt = render_chat_prompt(warm_turn_context, turn_plan=warm_turn_plan)
        explicit_packet = self.memory.sidecar_packet(
            "remember previous history",
            context={**warm_context, "message_id": f"accept-stage26-recall-{run_id}", "event_id": "2602"},
        )

        reloaded_task_world = {}
        reopened = MemoryBridge(
            self.config.runtime.repo_root,
            top_k=self.config.memory.prompt_top_k,
            graph_db_path=self.config.memory.mind_graph_db_path,
            stream_cadences=stream_cadences_from_config(self.config),
            graph_led_reply=self.config.memory.graph_led_reply,
            graph_fallback=self.config.memory.graph_fallback,
            deep_recall_on_memory_queries=self.config.memory.deep_recall_on_memory_queries,
            active_wechat_history_enabled=self.config.memory.active_wechat_history_enabled,
            vector_backend=self.config.memory.vector_backend,
            milvus_uri=self.config.memory.milvus_uri,
            milvus_collection_prefix=self.config.memory.milvus_collection_prefix,
            activation_cache_enabled=self.config.memory.activation_cache_enabled,
            private_memory_sync_enabled=self.config.memory.private_memory_sync_enabled,
            private_memory_repo_path=self.config.memory.private_memory_repo_path,
            stage25_max_hot_threads_per_cycle=self.config.memory.stage25_max_hot_threads_per_cycle,
            stage25_per_thread_pulse_budget=self.config.memory.stage25_per_thread_pulse_budget,
            stage25_skip_cold_without_pressure=self.config.memory.stage25_skip_cold_without_pressure,
            stage25_max_dense_working_set_threads=self.config.memory.stage25_max_dense_working_set_threads,
            stage25_cooldown_seconds_by_stream={
                "maintenance_stream": self.config.memory.stage25_maintenance_stream_cooldown_seconds,
                "association_stream": self.config.memory.stage25_association_stream_cooldown_seconds,
                "social_stream": self.config.memory.stage25_social_stream_cooldown_seconds,
                "deep_dream_cycle": self.config.memory.stage25_deep_dream_cycle_cooldown_seconds,
            },
            rag=self.memory.rag,
        )
        try:
            reloaded_task_world = reopened.show_task_world(
                thread_key=probe_thread_key,
                chat_name=probe_chat_name,
                channel=normalized_channel,
                limit=8,
                include_inactive=True,
            )
        finally:
            reopened.activation.close()
            reopened.graph.close()

        task_world_objects = list(task_world.get("objects", []))
        task_world_types = {str(item.get("object_type", "") or "") for item in task_world_objects}
        reloaded_objects = list(reloaded_task_world.get("objects", []))
        checks = {
            "stage25_acceptance_green": str(stage25_report.get("status", "")) == "pass",
            "task_world_persisted_across_restart": bool(reloaded_task_world.get("present", False))
            and len(reloaded_objects) >= 4
            and {"file", "task", "schedule", "image_summary", "person"}.issubset(
                {str(item.get("object_type", "") or "") for item in reloaded_objects}
            ),
            "required_object_families_visible": {"file", "task", "schedule", "image_summary", "person"}.issubset(task_world_types),
            "thread_and_commitment_links_are_inspectable": bool(link_trace.get("objects"))
            and any(list(item.get("linked_commitments", [])) for item in list(link_trace.get("objects", [])))
            and int(link_trace.get("cross_thread_object_count", 0) or 0) >= 1,
            "same_thread_reentry_uses_task_world_without_deep_recall": str(warm_packet.get("memory_route", "") or "") == "active_thread"
            and str(warm_packet.get("retrieval_mode", "") or "") == "active-thread-fast"
            and bool(dict(warm_packet.get("stage26", {})).get("task_world_used_for_thread", False))
            and str(warm_packet.get("tier", "") or "") != "deep_recall",
            "explicit_memory_query_still_escalates": str(explicit_packet.get("tier", "")).strip() in {"recall", "deep_recall"}
            and str(explicit_packet.get("recall_reason", "")).startswith("stage17:"),
            "stage22_compatibility_view_still_works": int(world_coupling.get("count", 0) or 0) >= 1
            and any(str(item.get("cue_type", "") or "") in {"file_artifact", "task_cue", "schedule_cue", "image_summary"} for item in list(world_coupling.get("items", []))),
            "prompt_remains_history_light": int(warm_turn_context.metadata.get("history_lines_in_prompt", 0) or 0) <= 1
            and "old line two" not in warm_prompt,
            "stage26_packet_visible": bool(dict(warm_packet.get("stage26", {})).get("task_world_visible", False))
            and bool(dict(warm_packet.get("stage26", {})).get("summary", "")),
            "object_trace_visible": bool(dict(object_trace.get("object", {})).get("object_id", "")),
        }
        return {
            "status": "pass" if all(checks.values()) else "fail",
            "stage": "bounded-task-world-state-stage26",
            "checks": checks,
            "thread_key": requested_thread_key,
            "chat_name": requested_chat_name,
            "channel": normalized_channel,
            "probe_thread_key": probe_thread_key,
            "stage25": {"status": stage25_report.get("status"), "checks": stage25_report.get("checks", {})},
            "file_artifact": file_artifact,
            "schedule_artifact": schedule_artifact,
            "task_world": task_world,
            "world_object": object_trace,
            "thread_object_links": link_trace,
            "world_coupling": world_coupling,
            "warm_packet": {
                "tier": warm_packet.get("tier"),
                "memory_route": warm_packet.get("memory_route"),
                "retrieval_mode": warm_packet.get("retrieval_mode"),
                "stage20": dict(warm_packet.get("stage20", {})),
                "stage24": dict(warm_packet.get("stage24", {})),
                "stage25": dict(warm_packet.get("stage25", {})),
                "stage26": dict(warm_packet.get("stage26", {})),
                "history_lines_in_prompt": int(warm_turn_context.metadata.get("history_lines_in_prompt", 0) or 0),
                "prompt_excerpt": compact_text(warm_prompt, 360),
            },
            "explicit_recall_probe": {
                "tier": explicit_packet.get("tier"),
                "recall_reason": explicit_packet.get("recall_reason"),
                "memory_route": explicit_packet.get("memory_route"),
            },
            "reloaded_task_world": reloaded_task_world,
            "objects_created": {
                "task": task_object,
                "person": person_object,
                "image_summary": image_object,
                "commitment": commitment,
                "shared_task": shared_task,
                "shared_task_other": shared_task_other,
            },
        }

    def _accept_stage27_impl(
        self,
        *,
        thread_key: str | None = None,
        chat_name: str | None = None,
        channel: str = "wechat",
        sender: str | None = None,
        artifact_dir: str | None = None,
    ) -> dict[str, Any]:
        normalized_channel = str(channel or "wechat").strip() or "wechat"
        requested_chat_name = str(chat_name or "TestUser").strip()
        requested_thread_key = str(thread_key or requested_chat_name).strip()
        if normalized_channel == "wechat":
            requested_thread_key = self._stage22_normalize_wechat_thread(requested_thread_key, requested_chat_name)
        stage26_report = self.accept_stage26(
            thread_key=requested_thread_key,
            chat_name=requested_chat_name,
            channel=normalized_channel,
            sender=sender,
            artifact_dir=artifact_dir,
        )
        run_id = stable_digest(requested_thread_key, requested_chat_name, utc_now(), "stage27")[:12]
        probe_chat_name = f"{requested_chat_name}-stage27-{run_id}"
        probe_thread_key = f"wechat:{probe_chat_name}" if normalized_channel == "wechat" else f"{requested_thread_key}:{run_id}"
        other_chat_name = f"{probe_chat_name}-other"
        other_thread_key = f"wechat:{other_chat_name}" if normalized_channel == "wechat" else f"{requested_thread_key}:other:{run_id}"
        artifact_root = Path(artifact_dir).resolve() / "stage27-blackbox" if str(artifact_dir or "").strip() else Path(tempfile.mkdtemp(prefix="holo-stage27-"))
        artifact_root.mkdir(parents=True, exist_ok=True)
        canary_root = artifact_root / "canary"
        canary_root.mkdir(parents=True, exist_ok=True)

        fragmented_a = self.memory.upsert_task_world_object(
            object_type="task",
            summary="shared blackbox deliverable awaiting continuation",
            thread_key=probe_thread_key,
            chat_name=probe_chat_name,
            channel=normalized_channel,
            source_ref="accept_stage27:fragmented",
            confidence=0.71,
            metadata={"source": "accept_stage27", "fragment": "a", "object_id": f"accept_stage27_fragment_a_{run_id}"},
        )
        fragmented_b = self.memory.upsert_task_world_object(
            object_type="task",
            summary="shared blackbox deliverable awaiting continuation",
            thread_key=other_thread_key,
            chat_name=other_chat_name,
            channel=normalized_channel,
            source_ref="accept_stage27:fragmented",
            confidence=0.7,
            metadata={"source": "accept_stage27", "fragment": "b", "object_id": f"accept_stage27_fragment_b_{run_id}"},
        )
        self.memory.archive_turn(
            "remind me where we left the deliverable",
            "We were still carrying the shared blackbox deliverable in this thread.",
            source="accept_stage27.seed",
            tags=["wechat", "chat_reply", "stage27"],
            metadata={"thread_key": probe_thread_key, "chat_name": probe_chat_name, "channel": normalized_channel},
        )
        sidecar = self.memory.sidecar_packet(
            "pick this up again without rereading everything",
            context={
                "channel": normalized_channel,
                "thread_key": probe_thread_key,
                "incoming_thread_key": probe_thread_key,
                "chat_name": probe_chat_name,
                "sender": str(sender or requested_chat_name),
                "message_id": f"accept-stage27-sidecar-{run_id}",
                "event_id": "2701",
                "attachments": [],
                "recent_history": [],
            },
        )
        task_world = self.show_task_world(
            thread_key=probe_thread_key,
            chat_name=probe_chat_name,
            channel=normalized_channel,
            limit=4,
            include_inactive=True,
        )
        identity_before = self.memory.self_model_state()
        autobiographical_before = self.memory.autobiographical_state()

        now = datetime.now(timezone.utc).replace(microsecond=0)
        timestamps = {
            "older": (now - timedelta(hours=30)).isoformat().replace("+00:00", "Z"),
            "shadow": (now - timedelta(hours=2)).isoformat().replace("+00:00", "Z"),
            "live": (now - timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
            "other": (now - timedelta(minutes=30)).isoformat().replace("+00:00", "Z"),
        }

        def _artifact_payload(
            *,
            thread_key: str,
            chat_name: str,
            message_id: str,
            text: str,
            mode: str,
            verdict: str,
            selected_action: str,
            returned_action: str,
            semantic_action: str,
            identity_continuity: float,
            chapter: str,
            latency_ms: int,
        ) -> dict[str, Any]:
            return {
                "event_row_id": 0,
                "thread_key": thread_key,
                "chat_name": chat_name,
                "input": {
                    "thread_key": thread_key,
                    "chat_name": chat_name,
                    "channel": normalized_channel,
                    "text": text,
                    "message_id": message_id,
                },
                "selected_action": {"action_type": selected_action},
                "semantic_action": semantic_action,
                "returned_action": returned_action,
                "result": {
                    "action": semantic_action,
                    "returned_action": returned_action,
                    "text": "I still have the same thread-local task-world in view.",
                    "delivery_suppressed_by_canary": verdict == "shadow_suppressed",
                },
                "gate": {"mode": mode, "verdict": verdict},
                "trace": {
                    "stage18": {"reply_lane": "micro_fast", "fast_lane": True},
                    "stage20": {"temporal_visible": True, "resume_cue": "pick the thread back up"},
                    "stage24": self._stage27_stage24_summary(dict(sidecar.get("stage24", {}))),
                    "stage25": self._stage27_stage25_summary(dict(sidecar.get("stage25", {}))),
                    "stage26": self._stage27_stage26_summary(dict(sidecar.get("stage26", {}))),
                },
                "identity_snapshot": {
                    "identity_continuity": round(float(identity_continuity), 4),
                    "current_chapter": chapter,
                },
                "timing_ms": {"stage22_total_ms": int(latency_ms)},
            }

        seeded_rows: list[dict[str, Any]] = []
        trace_specs = [
            {
                "key": "older",
                "thread_key": probe_thread_key,
                "chat_name": probe_chat_name,
                "message_id": f"accept-stage27-older-{run_id}",
                "text": "yesterday's continuation point",
                "mode": "shadow",
                "verdict": "shadow_suppressed",
                "selected_action": "reply_once",
                "returned_action": "silence",
                "semantic_action": "reply_once",
                "identity_continuity": 0.58,
                "chapter": "early reentry",
                "latency_ms": 180,
            },
            {
                "key": "shadow",
                "thread_key": probe_thread_key,
                "chat_name": probe_chat_name,
                "message_id": f"accept-stage27-shadow-{run_id}",
                "text": "pick the same thread up now",
                "mode": "shadow",
                "verdict": "shadow_suppressed",
                "selected_action": "reply_once",
                "returned_action": "silence",
                "semantic_action": "reply_once",
                "identity_continuity": 0.72,
                "chapter": "stable continuation",
                "latency_ms": 220,
            },
            {
                "key": "live",
                "thread_key": probe_thread_key,
                "chat_name": probe_chat_name,
                "message_id": f"accept-stage27-live-{run_id}",
                "text": "continue cleanly without rereading history",
                "mode": "canary_live",
                "verdict": "allowed",
                "selected_action": "reply_once",
                "returned_action": "reply",
                "semantic_action": "reply_once",
                "identity_continuity": 0.74,
                "chapter": "stable continuation",
                "latency_ms": 320,
            },
            {
                "key": "other",
                "thread_key": other_thread_key,
                "chat_name": other_chat_name,
                "message_id": f"accept-stage27-other-{run_id}",
                "text": "this is still the shared deliverable from the other thread",
                "mode": "shadow",
                "verdict": "shadow_suppressed",
                "selected_action": "reply_once",
                "returned_action": "silence",
                "semantic_action": "reply_once",
                "identity_continuity": 0.73,
                "chapter": "stable continuation",
                "latency_ms": 260,
            },
        ]
        for index, spec in enumerate(trace_specs, start=1):
            artifact = _artifact_payload(**{k: v for k, v in spec.items() if k != "key"})
            artifact_path = canary_root / f"{spec['key']}.json"
            atomic_write_text(artifact_path, json.dumps(artifact, ensure_ascii=False, indent=2) + "\n")
            row = self.store.record_canary_trace(
                event_row_id=2700 + index,
                channel=normalized_channel,
                thread_key=spec["thread_key"],
                chat_name=spec["chat_name"],
                message_id=spec["message_id"],
                mode=spec["mode"],
                verdict=spec["verdict"],
                selected_action=spec["selected_action"],
                returned_action=spec["returned_action"],
                latency_ms=spec["latency_ms"],
                artifact_path=str(artifact_path),
                metadata={
                    "trace": dict(artifact.get("trace", {})),
                    "result": dict(artifact.get("result", {})),
                    "identity_snapshot": dict(artifact.get("identity_snapshot", {})),
                },
            )
            with self.store._lock:
                self.store.conn.execute(
                    "UPDATE online_canary_traces SET created_at = ? WHERE id = ?",
                    (timestamps[spec["key"]], int(row.get("id", 0) or 0)),
                )
                self.store.conn.commit()
                refreshed = self.store.conn.execute(
                    "SELECT * FROM online_canary_traces WHERE id = ?",
                    (int(row.get("id", 0) or 0),),
                ).fetchone()
            seeded_rows.append(self.store._canary_trace_from_row(dict(refreshed) if refreshed else row))

        self.memory.archive_turn(
            "pick the same thread up now",
            "Let’s keep the same thread warm and continue the shared deliverable without rereading everything.",
            source="accept_stage27.human_reference",
            tags=["wechat", "chat_reply", "stage27"],
            metadata={"thread_key": probe_thread_key, "chat_name": probe_chat_name, "channel": normalized_channel},
        )

        soak = self.run_blackbox_soak(since_hours=48.0, limit=32, artifact_dir=str(artifact_root), persist=True)
        identity_after = self.memory.self_model_state()
        autobiographical_after = self.memory.autobiographical_state()
        scorecard = dict(soak.get("scorecard", {}))
        replay_report = dict(soak.get("replay_report", {}))
        blind_export = dict(soak.get("blind_export", {}))
        gate = dict(soak.get("gate", {}))
        online_canary = dict(soak.get("online_canary", {}))
        replay = dict(replay_report.get("replay", {})) if isinstance(replay_report.get("replay", {}), dict) else {}
        export_files = [
            Path(str(blind_export.get("transcript_packets_path", "") or "")),
            Path(str(blind_export.get("comparison_bundles_path", "") or "")),
            Path(str(blind_export.get("human_vs_holo_review_packets_path", "") or "")),
            Path(str(blind_export.get("answer_key_path", "") or "")),
        ]
        transcript_text = export_files[0].read_text(encoding="utf-8") if export_files[0].exists() else ""
        review_text = export_files[2].read_text(encoding="utf-8") if export_files[2].exists() else ""
        answer_key_text = export_files[3].read_text(encoding="utf-8") if export_files[3].exists() else ""
        stage26_checks = dict(stage26_report.get("checks", {})) if isinstance(stage26_report.get("checks", {}), dict) else {}
        stage26_core_green = all(
            bool(stage26_checks.get(key, False))
            for key in (
                "same_thread_reentry_uses_task_world_without_deep_recall",
                "explicit_memory_query_still_escalates",
                "stage22_compatibility_view_still_works",
                "prompt_remains_history_light",
                "stage26_packet_visible",
                "object_trace_visible",
            )
        )
        checks = {
            "stage26_acceptance_green": str(stage26_report.get("status", "")) == "pass" or stage26_core_green,
            "scorecard_metrics_present": all(
                key in scorecard
                for key in (
                    "identity_drift_across_days",
                    "resume_success_after_interruption",
                    "reread_history_rate",
                    "clarification_thrash_rate",
                    "duplicate_followup_rate",
                    "latency_buckets_by_action_type",
                    "policy_regret_on_live_artifacts",
                    "raw_policy_regret_on_live_artifacts",
                    "cross_thread_fragmentation_rate",
                )
            ),
            "replay_report_exposes_raw_and_display_metrics": bool(dict(replay.get("aggregate_metrics", {})))
            and bool(dict(replay.get("raw_aggregate_metrics", {}))),
            "blind_packets_exported_and_anonymized": all(path.exists() for path in export_files)
            and probe_thread_key not in transcript_text
            and probe_chat_name not in transcript_text
            and "accept_stage27:fragmented" not in transcript_text
            and str(artifact_root).replace("\\", "/") not in transcript_text.replace("\\", "/")
            and probe_thread_key not in review_text
            and probe_chat_name not in review_text
            and "accept_stage27:fragmented" not in review_text
            and probe_thread_key not in answer_key_text
            and probe_chat_name not in answer_key_text,
            "canary_remains_bounded_and_reversible": str(online_canary.get("contract", "")) == "host_side_shadow_first_block_only"
            and bool(online_canary.get("artifact_capture", False))
            and "wechat:TestUser" in list(online_canary.get("whitelist_threads", [])),
            "gate_uses_raw_policy_regret_only": float(gate.get("raw_policy_regret_used_for_gate", 0.0) or 0.0)
            == float(scorecard.get("raw_policy_regret_on_live_artifacts", 0.0) or 0.0),
            "no_self_memory_mutation": identity_before == identity_after and autobiographical_before == autobiographical_after,
            "persisted_soak_run_visible": bool(dict(soak.get("persisted_run", {})).get("id", 0)),
            "comparison_bundle_generated_for_shadow_trace": int(dict(blind_export.get("packet_counts", {})).get("comparison_bundles", 0) or 0) >= 1
            and int(dict(blind_export.get("packet_counts", {})).get("review_packets", 0) or 0) >= 1,
            "fragmentation_metric_detects_split_family": float(scorecard.get("cross_thread_fragmentation_rate", 0.0) or 0.0) > 0.0,
        }
        return {
            "status": "pass" if all(checks.values()) else "fail",
            "stage": "long-horizon-blackbox-soak-stage27",
            "checks": checks,
            "thread_key": requested_thread_key,
            "chat_name": requested_chat_name,
            "channel": normalized_channel,
            "probe_thread_key": probe_thread_key,
            "stage26": {"status": stage26_report.get("status"), "checks": stage26_report.get("checks", {})},
            "task_world": task_world,
            "objects_created": {"fragmented_a": fragmented_a, "fragmented_b": fragmented_b},
            "seeded_trace_ids": [int(row.get("id", 0) or 0) for row in seeded_rows],
            "scorecard": scorecard,
            "replay_report": replay_report,
            "blind_export": blind_export,
            "gate": gate,
            "online_canary": online_canary,
            "persisted_run": soak.get("persisted_run", {}),
        }

    def _accept_stage28_impl(
        self,
        *,
        thread_key: str | None = None,
        chat_name: str | None = None,
        channel: str = "wechat",
        sender: str | None = None,
        artifact_dir: str | None = None,
    ) -> dict[str, Any]:
        normalized_channel = str(channel or "wechat").strip() or "wechat"
        requested_chat_name = str(chat_name or "TestUser").strip()
        requested_thread_key = str(thread_key or requested_chat_name).strip()
        if normalized_channel == "wechat":
            requested_thread_key = self._stage22_normalize_wechat_thread(requested_thread_key, requested_chat_name)
        stage27_report = self.accept_stage27(
            thread_key=requested_thread_key,
            chat_name=requested_chat_name,
            channel=normalized_channel,
            sender=sender,
            artifact_dir=artifact_dir,
        )

        identity_before = self.memory.self_model_state()
        autobiographical_before = self.memory.autobiographical_state()
        run_id = stable_digest(requested_thread_key, requested_chat_name, utc_now(), "stage28")[:12]
        probe_chat_name = f"{requested_chat_name}-stage28-{run_id}"
        probe_thread_key = f"wechat:{probe_chat_name}" if normalized_channel == "wechat" else f"{requested_thread_key}:stage28:{run_id}"
        visual_artifact_path = f"/tmp/holo-stage28-{run_id}.png"
        self.memory.graph.upsert_visual_memory(
            channel=normalized_channel,
            thread_key=probe_thread_key,
            chat_name=probe_chat_name,
            artifact_path=visual_artifact_path,
            media_type="image/png",
            scene_summary="interface adaptation screenshot with provider status and an unclear right-side button",
            objects=["interface adaptation panel", "provider status", "unclear right-side button"],
            text_ocr="Provider OK / Visual pending",
            mood_imagery="engineering debugging screenshot",
            thread_relevance=0.87,
            visual_anchors=["upper-left provider status", "right-side button is unclear"],
            metadata={
                "spatial_refs": ["upper-left: provider status", "right-side: unclear button"],
                "uncertainty_markers": ["right-side button meaning is unclear"],
                "revisit_needed": True,
                "perceptual_density": "dense",
                "source": "accept_stage28",
            },
        )
        self.memory.update_active_thread_state(
            channel=normalized_channel,
            thread_key=probe_thread_key,
            chat_name=probe_chat_name,
            direction="inbound",
            text="let's repair visual reading, API adaptation, and non-template followups as one kernel thread",
            message_id=f"accept-stage28-inbound-{run_id}",
            event_row_id=2801,
            metadata={"source": "accept_stage28", "_stage24_force_scene_hint": True},
        )
        self.memory.upsert_task_world_object(
            object_type="task",
            summary="repair Holo visual reading, API adaptation, and grounded inquiry shaping",
            thread_key=probe_thread_key,
            chat_name=probe_chat_name,
            channel=normalized_channel,
            source_ref=f"accept_stage28:task:{run_id}",
            confidence=0.78,
            metadata={"source": "accept_stage28", "family": "kernel_reform"},
        )

        probe_query = "continue"
        context = {
            "channel": normalized_channel,
            "thread_key": probe_thread_key,
            "incoming_thread_key": probe_thread_key,
            "chat_name": probe_chat_name,
            "sender": str(sender or requested_chat_name),
            "message_id": f"accept-stage28-sidecar-{run_id}",
            "event_id": "2801",
            "attachments": [],
            "recent_history": [
                {"direction": "inbound", "body_text": "old line one"},
                {"direction": "outbound", "body_text": "old line two"},
            ],
        }
        packet = self.memory.sidecar_packet(probe_query, context=context)
        turn_context = TurnContext(
            channel=normalized_channel,
            thread_key=probe_thread_key,
            chat_name=probe_chat_name,
            sender=str(sender or requested_chat_name),
            user_text=probe_query,
            sidecar=packet,
            mind_packet=packet,
            attention_state=build_attention_state(probe_query, channel=normalized_channel, metadata={}),
            emotion_state=dict(packet.get("state", {}).get("emotion_state", {})),
            history=list(context["recent_history"]),
            metadata={},
            capability_context={},
        )
        turn_plan = build_turn_plan(turn_context, self.config)
        prompt = render_chat_prompt(turn_context, turn_plan=turn_plan)
        explicit_packet = self.memory.sidecar_packet(
            "remember previous complete chat history before answering",
            context={**context, "message_id": f"accept-stage28-recall-{run_id}", "event_id": "2802"},
        )
        situational_diag = self.show_situational_field(
            query=probe_query,
            thread_key=probe_thread_key,
            chat_name=probe_chat_name,
            channel=normalized_channel,
        )
        visual_diag = self.trace_visual_field(
            thread_key=probe_thread_key,
            chat_name=probe_chat_name,
            channel=normalized_channel,
        )
        inquiry_trace = self.trace_inquiry_shaping(
            query=probe_query,
            thread_key=probe_thread_key,
            chat_name=probe_chat_name,
            channel=normalized_channel,
            limit=8,
        )
        identity_after = self.memory.self_model_state()
        autobiographical_after = self.memory.autobiographical_state()

        stage28 = dict(packet.get("stage28", {}))
        situational_field = dict(packet.get("situational_field", {}))
        visual_field = dict(packet.get("visual_field", {}))
        action_candidates = [dict(item) for item in list(packet.get("action_market", [])) if isinstance(item, dict)]
        reply_candidate = next((item for item in action_candidates if str(item.get("action_type", "") or "") in {"reply_once", "reply_multi"}), {})
        prompt_situational_index = prompt.find("Situational Field:")
        prompt_history_index = prompt.find("Recent Thread Window:")
        stage27_checks = dict(stage27_report.get("checks", {})) if isinstance(stage27_report.get("checks", {}), dict) else {}
        stage27_core_green = all(
            bool(stage27_checks.get(key, False))
            for key in (
                "scorecard_metrics_present",
                "replay_report_exposes_raw_and_display_metrics",
                "blind_packets_exported_and_anonymized",
                "canary_remains_bounded_and_reversible",
                "no_self_memory_mutation",
            )
        )
        checks = {
            "stage27_acceptance_green": str(stage27_report.get("status", "")) == "pass" or stage27_core_green,
            "situational_field_visible": bool(stage28.get("situational_field_visible", False))
            and bool(situational_field.get("field_summary", "")),
            "visual_field_visible": bool(stage28.get("visual_field_visible", False))
            and bool(visual_field.get("revisit_needed", False))
            and bool(list(visual_field.get("uncertainty_markers", []))),
            "visual_uncertainty_shapes_grounded_inquiry": str(situational_field.get("inquiry_style", "")) == "visual_uncertainty"
            and "visual_uncertainty" in str(reply_candidate.get("stage28_rationale", "")),
            "prompt_uses_situational_field_before_history": prompt_situational_index >= 0
            and (prompt_history_index < 0 or prompt_situational_index < prompt_history_index)
            and int(turn_context.metadata.get("history_lines_in_prompt", 0) or 0) <= 1
            and "old line two" not in prompt,
            "action_market_stage28_overlay_inspectable": bool(action_candidates)
            and all("stage28_delta" in item and "stage28_rationale" in item and "stage28_grounding_order" in item for item in action_candidates),
            "explicit_memory_query_still_escalates": str(explicit_packet.get("tier", "")).strip() in {"recall", "deep_recall"}
            and str(explicit_packet.get("recall_reason", "")).startswith("stage17:"),
            "diagnostics_visible": bool(dict(situational_diag.get("stage28", {})))
            and bool(dict(visual_diag.get("visual_field", {})))
            and bool(list(inquiry_trace.get("action_market", []))),
            "no_self_memory_mutation": identity_before == identity_after and autobiographical_before == autobiographical_after,
            "no_new_loop_or_second_brain_flags": not bool(stage28.get("second_brain_added", False))
            and not bool(stage28.get("unbounded_loop_added", False))
            and bool(stage28.get("hard_gate_preserved", False)),
        }
        return {
            "status": "pass" if all(checks.values()) else "fail",
            "stage": "multimodal-homeostatic-kernel-stage28",
            "checks": checks,
            "thread_key": requested_thread_key,
            "chat_name": requested_chat_name,
            "channel": normalized_channel,
            "probe_thread_key": probe_thread_key,
            "stage27": {"status": stage27_report.get("status"), "checks": stage27_report.get("checks", {})},
            "mind_packet": {
                "tier": packet.get("tier"),
                "memory_route": packet.get("memory_route"),
                "retrieval_mode": packet.get("retrieval_mode"),
                "stage24": dict(packet.get("stage24", {})),
                "stage25": dict(packet.get("stage25", {})),
                "stage26": dict(packet.get("stage26", {})),
                "stage28": stage28,
                "situational_field": situational_field,
                "visual_field": visual_field,
                "selected_action": dict(packet.get("selected_action", {})),
                "history_lines_in_prompt": int(turn_context.metadata.get("history_lines_in_prompt", 0) or 0),
                "prompt_excerpt": compact_text(prompt, 420),
            },
            "explicit_recall_probe": {
                "tier": explicit_packet.get("tier"),
                "recall_reason": explicit_packet.get("recall_reason"),
                "memory_route": explicit_packet.get("memory_route"),
            },
            "diagnostics": {
                "situational_field": situational_diag,
                "visual_field": visual_diag,
                "inquiry_shaping": inquiry_trace,
            },
        }

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
            selected_action = dict(packet.get("selected_action", {})) if isinstance(packet.get("selected_action", {}), dict) else {}
            if not str(selected_action.get("action_type", "")).strip() and str(getattr(reply_plan, "text", "") or "").strip():
                selected_action = {"action_type": "reply_once"}
            expression_budget = int(
                packet.get(
                    "expression_budget_v4",
                    packet.get(
                        "expression_budget_v3",
                        packet.get("expression_budget_v2", packet.get("expression_budget", 0)),
                    ),
                )
                or 0
            )
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
                "selected_action": selected_action,
                "selected_prediction": dict(packet.get("selected_prediction", {})),
                "expression_budget": expression_budget,
                "action_rationale": str(packet.get("action_rationale", "") or ""),
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
        probes["selected_action"] = dict(probes["graph_led"].get("selected_action", {}))
        probes["expression_budget"] = int(probes["graph_led"].get("expression_budget", 0) or 0)
        probes["action_rationale"] = str(probes["graph_led"].get("action_rationale", "") or "")
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

    def _stage22_canary_mode(self) -> str:
        mode = str(getattr(self.config.autonomy, "stage22_canary_mode", "shadow") or "shadow").strip().lower()
        if mode not in {"disabled", "shadow", "canary_live"}:
            return "shadow"
        return mode

    def _stage22_path(self, raw: str, *, fallback: str) -> Path:
        current = str(raw or fallback).strip() or fallback
        path = Path(current).expanduser()
        if not path.is_absolute():
            path = (self.config.runtime.repo_root / path).resolve()
        return path

    def _stage22_rollback_path(self) -> Path:
        return self._stage22_path(
            getattr(self.config.autonomy, "stage22_canary_rollback_file", ".holo_runtime/STAGE22_CANARY_ROLLBACK"),
            fallback=".holo_runtime/STAGE22_CANARY_ROLLBACK",
        )

    def _stage22_artifact_root(self) -> Path:
        return self._stage22_path(
            getattr(self.config.autonomy, "stage22_canary_artifact_root", "artifacts/canary/stage22"),
            fallback="artifacts/canary/stage22",
        )

    @staticmethod
    def _stage22_normalize_wechat_thread(thread_key: str, chat_name: str = "") -> str:
        current = str(thread_key or "").strip()
        name = str(chat_name or "").strip()
        while current.startswith("wechat:wechat:"):
            current = "wechat:" + current[len("wechat:wechat:") :]
        if not current:
            current = name
        if current.startswith("wechat:") or current.endswith("@chatroom") or current.startswith("wxid_"):
            return current
        return f"wechat:{current}" if current else ""

    def _stage22_whitelist_threads(self) -> list[str]:
        configured = [
            self._stage22_normalize_wechat_thread(str(item), str(item))
            for item in getattr(self.config.autonomy, "stage22_canary_whitelist_threads", ())
            if str(item).strip()
        ]
        if configured:
            return sorted(set(configured))
        helper = self._load_wechat_helper_runtime()
        return sorted(
            {
                self._stage22_normalize_wechat_thread(str(item), str(item))
                for item in list(helper.get("whitelist", []))
                if str(item).strip()
            }
        )

    def _stage22_trace_from_sidecar(self, sidecar: dict[str, Any]) -> dict[str, Any]:
        market = list(sidecar.get("action_market_v4", sidecar.get("action_market", [])))
        return {
            "stage18": dict(sidecar.get("stage18", {})),
            "stage19": {
                key: value
                for key, value in dict(sidecar.get("stage19", {})).items()
                if key in {"frontier_used_for_thread", "thread_heat", "thread_warmth", "wake_reason", "unresolved_thread_pull"}
            },
            "stage20": {
                key: value
                for key, value in dict(sidecar.get("stage20", {})).items()
                if key in {"temporal_visible", "temporal_used_for_thread", "resume_cue", "commitment_due", "duplicate_recovery_blocked"}
            },
            "stage21": dict(sidecar.get("stage21", {})),
            "stage22": dict(sidecar.get("stage22", {})),
            "stage24": self._stage27_stage24_summary(dict(sidecar.get("stage24", {}))),
            "stage25": self._stage27_stage25_summary(dict(sidecar.get("stage25", {}))),
            "stage26": self._stage27_stage26_summary(dict(sidecar.get("stage26", {}))),
            "tier": str(sidecar.get("tier", "") or ""),
            "memory_route": str(sidecar.get("memory_route", "") or ""),
            "retrieval_mode": str(sidecar.get("retrieval_mode", "") or ""),
            "recall_reason": str(sidecar.get("recall_reason", "") or ""),
            "top_actions": [
                str(item.get("action_type", "") or "")
                for item in market[:5]
                if isinstance(item, dict) and str(item.get("action_type", "") or "").strip()
            ],
        }

    def _stage22_canary_gate(
        self,
        *,
        turn: ChatTurn,
        incoming: IncomingMessage,
        selected_action: dict[str, Any],
        sidecar: dict[str, Any],
    ) -> dict[str, Any]:
        mode = self._stage22_canary_mode()
        selected_type = str(selected_action.get("action_type", "") or "reply_once")
        whitelist = self._stage22_whitelist_threads() if turn.channel == "wechat" else []
        canonical_thread = incoming.thread_key
        whitelisted = True if turn.channel != "wechat" else canonical_thread in set(whitelist)
        rollback_path = self._stage22_rollback_path()
        rollback_enabled = rollback_path.exists()
        cutoff = (datetime.now(timezone.utc).replace(microsecond=0) - timedelta(hours=1)).isoformat().replace("+00:00", "Z")
        per_thread_count = self.store.count_canary_live_replies(since=cutoff, channel=turn.channel, thread_key=canonical_thread)
        global_count = self.store.count_canary_live_replies(since=cutoff, channel=turn.channel)
        per_thread_limit_raw = getattr(self.config.autonomy, "stage22_canary_max_replies_per_thread_per_hour", 12)
        global_limit_raw = getattr(self.config.autonomy, "stage22_canary_max_replies_global_per_hour", 30)
        per_thread_limit = max(0, int(12 if per_thread_limit_raw is None else per_thread_limit_raw))
        global_limit = max(0, int(30 if global_limit_raw is None else global_limit_raw))
        per_thread_ok = per_thread_count < per_thread_limit
        global_ok = global_count < global_limit
        allowed = mode == "disabled" or (
            mode == "canary_live"
            and whitelisted
            and not rollback_enabled
            and per_thread_ok
            and global_ok
        )
        verdict = "disabled"
        if mode == "shadow":
            verdict = "shadow_suppressed"
        elif mode == "canary_live":
            if not whitelisted:
                verdict = "not_whitelisted"
            elif rollback_enabled:
                verdict = "rollback_enabled"
            elif not per_thread_ok:
                verdict = "thread_rate_limited"
            elif not global_ok:
                verdict = "global_rate_limited"
            else:
                verdict = "allowed"
        return {
            "stage": "stage22",
            "mode": mode,
            "allowed": bool(allowed),
            "verdict": verdict,
            "selected_action": selected_type,
            "thread_key": canonical_thread,
            "chat_name": turn.chat_name,
            "channel": turn.channel,
            "whitelist": whitelist,
            "whitelisted": bool(whitelisted),
            "rollback_enabled": bool(rollback_enabled),
            "rollback_path": str(rollback_path),
            "rate_limits": {
                "per_thread": {"count": per_thread_count, "limit": per_thread_limit, "ok": per_thread_ok},
                "global": {"count": global_count, "limit": global_limit, "ok": global_ok},
            },
            "artifact_capture": bool(getattr(self.config.autonomy, "stage22_canary_artifact_capture", True)),
            "hard_gate_preserved": True,
            "trace": self._stage22_trace_from_sidecar(sidecar),
        }

    @staticmethod
    def _stage23_is_delivery_capable_action(action: str) -> bool:
        return str(action or "").strip() in {"reply", "defer_reply"}

    @classmethod
    def _stage23_finalize_result_contract(
        cls,
        result: dict[str, Any],
        *,
        returned_action: str | None = None,
        delivery_verdict: str = "",
        delivery_send_allowed: bool | None = None,
        delivery_suppressed_by_canary: bool | None = None,
    ) -> dict[str, Any]:
        semantic_action = str(result.get("semantic_action", result.get("action", "")) or "")
        semantic_reason = str(result.get("semantic_reason", result.get("reason", "")) or "")
        delivery_capable = cls._stage23_is_delivery_capable_action(semantic_action)
        realized_action = str(returned_action or result.get("returned_action", semantic_action) or semantic_action)
        if delivery_send_allowed is None:
            delivery_send_allowed = delivery_capable and realized_action == semantic_action
        if not delivery_verdict:
            delivery_verdict = "allowed" if delivery_capable and delivery_send_allowed else "not_applicable"
        if delivery_suppressed_by_canary is None:
            delivery_suppressed_by_canary = (
                delivery_capable
                and not delivery_send_allowed
                and realized_action != semantic_action
                and str(delivery_verdict or "").strip() not in {"", "not_applicable"}
            )
        result["semantic_action"] = semantic_action
        result["semantic_reason"] = semantic_reason
        result["action"] = semantic_action
        result["reason"] = semantic_reason
        result["returned_action"] = realized_action
        result["delivery_verdict"] = str(delivery_verdict or "not_applicable")
        result["delivery_send_allowed"] = bool(delivery_send_allowed) if delivery_capable else False
        result["delivery_suppressed_by_canary"] = bool(delivery_suppressed_by_canary)
        result.setdefault("stage22_shadow", False)
        return result

    @classmethod
    def _stage23_gate_for_result(cls, gate: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(gate)
        semantic_action = str(result.get("semantic_action", result.get("action", "")) or "")
        if cls._stage23_is_delivery_capable_action(semantic_action):
            return normalized
        normalized["allowed"] = True
        normalized["verdict"] = "not_applicable"
        return normalized

    def _stage22_shadow_result(
        self,
        *,
        turn: ChatTurn,
        incoming: IncomingMessage,
        event_row_id: int,
        selected_action: dict[str, Any],
        result: dict[str, Any],
        gate: dict[str, Any],
        sidecar: dict[str, Any],
        latency_ms: int,
    ) -> dict[str, Any]:
        shadow_result = self._stage23_finalize_result_contract(
            dict(result),
            returned_action="silence",
            delivery_verdict=str(gate.get("verdict", "stage22_shadow") or "stage22_shadow"),
            delivery_send_allowed=False,
            delivery_suppressed_by_canary=self._stage23_is_delivery_capable_action(str(result.get("action", ""))),
        )
        shadow_result["stage22_shadow"] = bool(shadow_result.get("delivery_suppressed_by_canary")) and str(gate.get("mode", "")) == "shadow"
        normalized_gate = self._stage23_gate_for_result(gate, shadow_result)
        shadow_result["stage22"] = self._record_stage22_canary(
            turn=turn,
            incoming=incoming,
            event_row_id=event_row_id,
            selected_action=selected_action,
            sidecar=sidecar,
            gate=normalized_gate,
            result=shadow_result,
            latency_ms=latency_ms,
        )
        status = "silenced" if bool(shadow_result.get("delivery_suppressed_by_canary")) else "completed"
        self.store.update_event_result(event_row_id, status=status, result=shadow_result)
        if bool(shadow_result.get("delivery_suppressed_by_canary")):
            self._record_consciousness_entry(
                turn=turn,
                incoming=incoming,
                event_row_id=event_row_id,
                entry_type="stage22_canary_suppressed",
                selected_action=str(selected_action.get("action_type", "") or ""),
                payload=shadow_result,
            )
        return shadow_result

    def _record_stage22_canary(
        self,
        *,
        turn: ChatTurn,
        incoming: IncomingMessage,
        event_row_id: int,
        selected_action: dict[str, Any],
        sidecar: dict[str, Any],
        gate: dict[str, Any],
        result: dict[str, Any],
        latency_ms: int,
    ) -> dict[str, Any]:
        if str(gate.get("mode", "")) == "disabled":
            return dict(gate)
        artifact_path = ""
        identity_snapshot = self._stage27_identity_snapshot()
        trace_payload = {
            "schema_version": "stage22.canary.v1",
            "captured_at": utc_now(),
            "event_row_id": int(event_row_id or 0),
            "input": {
                "channel": turn.channel,
                "thread_key": incoming.thread_key,
                "chat_name": turn.chat_name,
                "message_id": incoming.message_id,
                "text": compact_text(turn.text, 500),
                "source_ref": turn.source_ref,
                "attachments": list((turn.metadata or {}).get("attachments", []))[:4] if isinstance((turn.metadata or {}).get("attachments", []), list) else [],
            },
            "selected_action": dict(selected_action),
            "semantic_action": str(result.get("semantic_action", result.get("action", "")) or ""),
            "returned_action": str(result.get("returned_action", result.get("action", "")) or ""),
            "result": {
                "action": str(result.get("action", "") or ""),
                "semantic_action": str(result.get("semantic_action", result.get("action", "")) or ""),
                "semantic_reason": str(result.get("semantic_reason", result.get("reason", "")) or ""),
                "returned_action": str(result.get("returned_action", result.get("action", "")) or ""),
                "delivery_verdict": str(result.get("delivery_verdict", "") or ""),
                "delivery_send_allowed": bool(result.get("delivery_send_allowed", False)),
                "delivery_suppressed_by_canary": bool(result.get("delivery_suppressed_by_canary", False)),
                "reason": str(result.get("reason", "") or ""),
                "text": compact_text(str(result.get("text", "") or ""), 500),
                "bubbles": [compact_text(str(item), 200) for item in list(result.get("bubbles", []))[:4]],
            },
            "gate": {key: value for key, value in dict(gate).items() if key != "trace"},
            "trace": self._stage22_trace_from_sidecar(sidecar),
            "identity_snapshot": identity_snapshot,
            "timing_ms": {
                **(dict(result.get("timing_ms", {})) if isinstance(result.get("timing_ms", {}), dict) else {}),
                "stage22_total_ms": max(0, int(latency_ms or 0)),
            },
        }
        if bool(getattr(self.config.autonomy, "stage22_canary_artifact_capture", True)):
            root = self._stage22_artifact_root() / time.strftime("%Y%m%d")
            filename = f"{int(event_row_id or 0)}-{stable_digest(incoming.thread_key, incoming.message_id, str(result.get('returned_action', result.get('action', ''))), limit=12)}.json"
            artifact = root / filename
            artifact.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_text(artifact, json.dumps(trace_payload, ensure_ascii=False, indent=2) + "\n")
            artifact_path = str(artifact)
        row = self.store.record_canary_trace(
            event_row_id=event_row_id,
            channel=turn.channel,
            thread_key=incoming.thread_key,
            chat_name=turn.chat_name,
            message_id=incoming.message_id,
            mode=str(gate.get("mode", "shadow") or "shadow"),
            verdict=str(gate.get("verdict", "") or ""),
            selected_action=str(selected_action.get("action_type", "") or ""),
            returned_action=str(result.get("returned_action", result.get("action", "")) or ""),
            latency_ms=max(0, int(latency_ms or 0)),
            artifact_path=artifact_path,
            metadata={
                "gate": {key: value for key, value in dict(gate).items() if key != "trace"},
                "trace": trace_payload["trace"],
                "result": trace_payload["result"],
                "identity_snapshot": identity_snapshot,
                "timing_ms": trace_payload["timing_ms"],
            },
        )
        return {
            **{key: value for key, value in dict(gate).items() if key != "trace"},
            "artifact_path": artifact_path,
            "trace_id": int(row.get("id", 0) or 0),
            "latency_bucket": str(row.get("latency_bucket", "")),
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
        explicit_request = any(marker in query for marker in WECHAT_HISTORY_EXPLICIT_HINTS)
        intent = {}
        for key in ("intent_state_v4", "intent_state_v3", "intent_state_v2", "intent_state"):
            candidate = sidecar.get(key, {})
            if isinstance(candidate, dict):
                intent = candidate
                break
        explicit_memory_request = bool(intent.get("local_memory_requested") or intent.get("search_requested"))
        recall_reason = str(sidecar.get("recall_reason", "") or str(dict(sidecar.get("stage17", {})).get("recall_escalation_reason", ""))).strip()
        if explicit_memory_request or recall_reason in {"stage17:explicit_memory_query", "explicit_memory_query"}:
            return True
        if str(sidecar.get("query_focus", "") or "") == "origin" and str(sidecar.get("tier", "")).strip().lower() in {"recall", "deep_recall"}:
            return True
        return explicit_request

    @staticmethod
    def _demote_nonblocking_history_refresh(sidecar: dict[str, Any], *, reason: str = "explicit_on_demand") -> tuple[dict[str, Any], str, dict[str, Any]]:
        selected = dict(sidecar.get("selected_action", {}))
        selected_type = str(selected.get("action_type", "reply_once") or "reply_once")
        report = {}
        if selected_type != "history_refresh":
            return selected, selected_type, report
        replacement = next(
            (
                dict(item)
                for item in list(sidecar.get("action_market", []))
                if str(item.get("action_type", "")).strip() in {"reply_once", "reply_multi", "push_back", "counter_offer", "continuity_defense"}
            ),
            {"action_type": "reply_once", "why_now": "history refresh was demoted off the live path", "score": 0.0, "send_allowed": True},
        )
        sidecar["selected_action"] = replacement
        selected_type = str(replacement.get("action_type", "reply_once") or "reply_once")
        stage17 = dict(sidecar.get("stage17", {}))
        stage17["refresh_demoted"] = reason
        stage17["active_history_refresh_blocking"] = False
        sidecar["stage17"] = stage17
        report = {
            "status": "demoted",
            "reason": reason,
            "selected_action_before": "history_refresh",
            "selected_action_after": selected_type,
        }
        return replacement, selected_type, report

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
        event_row_id: int | None = None,
    ) -> int:
        available_at = (
            datetime.now(timezone.utc).replace(microsecond=0)
            + timedelta(seconds=max(90, int(self.config.memory.attention_tick_interval_seconds) * 20))
        ).isoformat().replace("+00:00", "Z")
        source_event_id = str(event_row_id or stored_message.get("id", "") or turn.message_id or "").strip()
        dedupe_key = f"deferred_reply:{turn.channel}:{thread.get('thread_key') or turn.normalized_thread_key}:{stored_message.get('message_id') or turn.message_id or source_event_id}"
        existing = self.store.find_pending_job_by_dedupe_key(int(thread["id"]), dedupe_key=dedupe_key, task_type="deferred_reply")
        if existing:
            return int(existing["id"])
        job_id = self.store.enqueue_job(
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
                "dedupe_key": dedupe_key,
                "selected_action": dict(selected_action),
            },
        )
        if hasattr(self.memory.graph, "upsert_temporal_item"):
            self.memory.graph.upsert_temporal_item(
                item_type="deferred_intention",
                channel=turn.channel,
                thread_key=str(thread.get("thread_key") or turn.normalized_thread_key),
                chat_name=turn.chat_name,
                confidence=0.72,
                source_event_id=source_event_id,
                source_action_ref=str(job_id),
                source_action_type="defer_reply",
                due_at=available_at,
                revisit_after=available_at,
                resume_cue=defer_reason or turn.text,
                dedupe_key=dedupe_key,
                status="scheduled",
                queue_job_id=job_id,
                metadata={
                    "source": "reply_api.defer_reply",
                    "selected_action": dict(selected_action),
                    "message_id": str(stored_message.get("message_id") or turn.message_id or ""),
                    "evidence_refs": [f"event:{source_event_id}", f"job:{job_id}"],
                },
            )
            self.memory.graph.upsert_temporal_item(
                item_type="commitment",
                channel=turn.channel,
                thread_key=str(thread.get("thread_key") or turn.normalized_thread_key),
                chat_name=turn.chat_name,
                confidence=0.7,
                source_event_id=source_event_id,
                source_action_ref=str(job_id),
                source_action_type="defer_reply",
                due_at=available_at,
                revisit_after=available_at,
                resume_cue=defer_reason or turn.text,
                dedupe_key=f"commitment:{dedupe_key}",
                status="scheduled",
                queue_job_id=job_id,
                metadata={
                    "source": "reply_api.defer_reply",
                    "selected_action": dict(selected_action),
                    "message_id": str(stored_message.get("message_id") or turn.message_id or ""),
                    "evidence_refs": [f"event:{source_event_id}", f"job:{job_id}"],
                },
            )
            self.memory.clear_packet_cache()
        return job_id

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

    @staticmethod
    def _stage17_unresolved_references(text: str) -> list[str]:
        lowered = str(text or "").lower()
        hints = (
            "that",
            "this",
            "it",
            "above",
            "earlier",
            "刚才",
            "刚刚",
            "那个",
            "这个",
            "那件事",
            "这件事",
            "上面",
            "前面",
        )
        return [hint for hint in hints if hint in lowered][:5]

    @staticmethod
    def _stage17_affect_hint(text: str, *, attention_focus: str = "") -> str:
        lowered = str(text or "").lower()
        if any(token in lowered for token in ("累", "压力", "难受", "anxious", "tired", "stress")):
            return "pressure"
        if any(token in lowered for token in ("想你", "陪", "在吗", "still there")):
            return "companionship"
        if any(token in lowered for token in ("?", "？", "怎么", "为什么", "how", "why", "what")):
            return "curiosity"
        return attention_focus or "ordinary"

    def _stage24_scene_compression_hint(
        self,
        *,
        turn: ChatTurn,
        incoming: IncomingMessage,
        direction: str,
        text: str,
        action_type: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        normalized_text = " ".join(str(text or "").strip().split())
        lowered = normalized_text.lower()
        turn_metadata = dict(turn.metadata) if isinstance(turn.metadata, dict) else {}
        if not normalized_text:
            return {}
        if list((metadata or {}).get("attachments", []) or turn_metadata.get("attachments", []) or []):
            return {}
        if any(hint in lowered for hint in ("remember", "history", "earlier", "previous", "search", "look up", "latest", "official", "image", "photo", "picture")):
            return {}
        if len(normalized_text) < 180 and (normalized_text.count("?") + normalized_text.count("？")) < 2:
            return {}
        prompt = (
            "Return JSON only with keys shared_frame, topic_stack, salient_objects, latent_questions, "
            "predicted_branches, relationship_trajectory, response_sketch, scene_confidence.\n"
            f"direction={direction}\n"
            f"channel={turn.channel}\n"
            f"thread_key={incoming.thread_key}\n"
            f"chat_name={turn.chat_name}\n"
            f"action_type={action_type}\n"
            f"text={normalized_text}\n"
            "Constraints: compact summaries only, topic_stack<=4, salient_objects<=4, latent_questions<=3, "
            "predicted_branches<=3, scene_confidence in [0,1], no raw history dump."
        )
        try:
            result = self.runner.run_task(
                ProcessorTaskRequest(
                    task_type="reflect",
                    prompt=prompt,
                    output_schema="json",
                    budget_tag="scene_state",
                    max_output_tokens=320,
                    metadata={"raw_prompt": True, "stage": "stage24", "thread_key": incoming.thread_key},
                )
            )
            if int(result.returncode or 0) != 0:
                return {"mode": "heuristic_fallback", "reason": "processor_returncode", "detail": str(result.stderr or result.stdout or "")}
            parsed = json.loads(str(result.text or "{}"))
            if not isinstance(parsed, dict):
                raise ValueError("scene compression payload must be a dict")
            return {"mode": "processor", "reason": "processor_scene_compression", "scene_state": parsed}
        except Exception as exc:  # noqa: BLE001
            return {"mode": "heuristic_fallback", "reason": "processor_unavailable", "detail": str(exc)}

    def _update_active_thread_state(
        self,
        *,
        turn: ChatTurn,
        incoming: IncomingMessage,
        direction: str,
        event_row_id: int | None = None,
        text: str = "",
        action_type: str = "",
        selected_action: dict[str, Any] | None = None,
        intent_state: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not hasattr(self.memory, "update_active_thread_state"):
            return {"status": "skipped", "reason": "active_thread_state_unavailable"}
        attention = build_attention_state(text or turn.text, channel=turn.channel, metadata=turn.metadata)
        scene_hint = self._stage24_scene_compression_hint(
            turn=turn,
            incoming=incoming,
            direction=direction,
            text=text or turn.text,
            action_type=action_type or str((selected_action or {}).get("action_type", "") or ""),
            metadata=metadata,
        )
        extra_metadata = dict(metadata or {})
        if scene_hint:
            extra_metadata["_stage24_scene_compression"] = {key: value for key, value in scene_hint.items() if key != "scene_state"}
            if isinstance(scene_hint.get("scene_state"), dict):
                extra_metadata["_stage24_scene_hint"] = dict(scene_hint.get("scene_state", {}))
        try:
            with self._memory_lock:
                return self.memory.update_active_thread_state(
                    channel=turn.channel,
                    thread_key=incoming.thread_key,
                    chat_name=turn.chat_name,
                    direction=direction,
                    text=text or turn.text,
                    message_id=incoming.message_id,
                    event_row_id=event_row_id,
                    action_type=action_type,
                    selected_action=selected_action,
                    intent_state=intent_state,
                    attention_focus=attention.primary_focus,
                    active_affect_hint=self._stage17_affect_hint(text or turn.text, attention_focus=attention.primary_focus),
                    relationship_tension=0.0 if attention.pressure_level != "high" else 0.72,
                    unresolved_references=self._stage17_unresolved_references(text or turn.text),
                    metadata=extra_metadata,
                )
        except Exception as exc:  # noqa: BLE001
            self.logger.debug("active thread state update skipped for %s: %s", turn.chat_name, exc)
            return {"status": "skipped", "reason": "active_thread_state_error", "detail": str(exc)}

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

    @staticmethod
    def _appraisable_reply_action(action_type: str) -> bool:
        return action_type in {"silence", "defer_reply", "reply_once", "reply_multi", "push_back", "counter_offer", "continuity_defense"}

    def _action_local_usage_payload(
        self,
        *,
        event_row_id: int | None,
        thread_key: str,
        action_ref: str,
    ) -> dict[str, Any]:
        rows: list[dict[str, Any]] = []
        evidence_refs: list[str] = []
        if event_row_id:
            rows = self.store.list_processor_usage(limit=16, event_id=str(event_row_id), thread_key=thread_key)
            if rows:
                evidence_refs.append(f"usage:event_id:{event_row_id}")
        simplified_rows = [
            {
                "id": int(row.get("id", 0) or 0),
                "task_type": str(row.get("task_type", "") or ""),
                "lane": str(row.get("lane", "") or ""),
                "provider": str(row.get("provider", "") or ""),
                "model": str(row.get("model", "") or ""),
                "total_tokens": int(row.get("total_tokens", 0) or 0),
                "event_id": str(row.get("event_id", "") or ""),
                "created_at": str(row.get("created_at", "") or ""),
            }
            for row in rows
        ]
        if not evidence_refs:
            evidence_refs.append(f"usage:none_for_action_ref:{action_ref}")
        return {
            "usage_total_tokens": sum(int(row.get("total_tokens", 0) or 0) for row in rows),
            "usage_rows": simplified_rows,
            "usage_evidence_refs": evidence_refs,
        }

    def _appraise_reply_path_action(
        self,
        *,
        turn: ChatTurn,
        incoming: IncomingMessage,
        thread: dict[str, Any],
        stored_message: dict[str, Any],
        event_row_id: int | None,
        sidecar: dict[str, Any],
        action_type: str,
        action_ref: str,
        source: str,
    ) -> dict[str, Any]:
        def _metric(raw: Any, default: float = 0.0) -> float:
            try:
                if isinstance(raw, dict):
                    raw = raw.get("value", default)
                return max(0.0, min(1.0, float(raw)))
            except (TypeError, ValueError):
                return float(default)

        if not hasattr(self.memory, "appraise_outcome"):
            return {"status": "skipped", "reason": "memory_appraisal_unavailable"}
        if not self._appraisable_reply_action(action_type):
            return {"status": "skipped", "reason": "non_appraisable_action"}
        normalized_action_ref = str(action_ref or "").strip()
        if not normalized_action_ref:
            return {"status": "skipped", "reason": "missing_action_ref"}
        selected_prediction = dict(sidecar.get("selected_prediction", {}))
        usage_payload = self._action_local_usage_payload(
            event_row_id=event_row_id,
            thread_key=incoming.thread_key,
            action_ref=normalized_action_ref,
        )
        metadata = {
            "event_row_id": int(event_row_id or 0),
            "message_id": incoming.message_id,
            "thread_key": incoming.thread_key,
            "selected_action": action_type,
            "selected_prediction": selected_prediction,
            "source": source,
            **usage_payload,
        }
        if action_type in {"silence", "defer_reply"}:
            predicted_response_quality = _metric(selected_prediction.get("predicted_response_quality"), default=0.5)
            predicted_risk = _metric(selected_prediction.get("predicted_risk"), default=0.5)
            predicted_relational_delta = _metric(selected_prediction.get("predicted_relational_delta"), default=0.0)
            predicted_identity_delta = _metric(selected_prediction.get("predicted_identity_delta"), default=0.0)
            metadata["evidence_refs"] = list(usage_payload["usage_evidence_refs"]) + [
                "messages:current_turn",
                "prediction:selected_outcome",
                f"action:{action_type}",
            ]
            return self.memory.appraise_outcome(
                channel=turn.channel,
                thread_key=incoming.thread_key,
                chat_name=turn.chat_name,
                action_type=action_type,
                action_ref=normalized_action_ref,
                was_rewarding=max(0.0, min(1.0, (predicted_response_quality + max(0.0, 1.0 - predicted_risk)) / 2.0)),
                was_ignored=0.0,
                relational_delta=predicted_relational_delta,
                identity_delta=predicted_identity_delta,
                future_initiative_bias=max(0.0, predicted_relational_delta - predicted_risk * 0.25),
                future_resistance_bias=predicted_risk,
                metadata=metadata,
            )

        from .daemon import HoloDaemon

        recent_messages = list(reversed(self.store.recent_thread_messages(int(thread["id"]), limit=12)))
        evidence_payload = HoloDaemon._derive_action_outcome_from_evidence(
            sent_at=stored_message.get("created_at"),
            recent_messages=recent_messages,
            predicted_outcome=selected_prediction,
            usage_rows=list(usage_payload.get("usage_rows", [])),
            usage_evidence_refs=list(usage_payload.get("usage_evidence_refs", [])),
        )
        evidence_payload["evidence_refs"] = [str(item).strip() for item in list(evidence_payload.get("evidence_refs", [])) if str(item).strip()]
        metadata.update(evidence_payload)
        return self.memory.appraise_outcome(
            channel=turn.channel,
            thread_key=incoming.thread_key,
            chat_name=turn.chat_name,
            action_type=action_type,
            action_ref=normalized_action_ref,
            was_rewarding=float(evidence_payload.get("was_rewarding", 0.0) or 0.0),
            was_ignored=float(evidence_payload.get("was_ignored", 0.0) or 0.0),
            relational_delta=float(evidence_payload.get("relational_delta", 0.0) or 0.0),
            identity_delta=float(evidence_payload.get("identity_delta", 0.0) or 0.0),
            future_initiative_bias=float(evidence_payload.get("future_initiative_bias", 0.0) or 0.0),
            future_resistance_bias=float(evidence_payload.get("future_resistance_bias", 0.0) or 0.0),
            metadata=metadata,
        )

    @staticmethod
    def _appraisable_actions() -> set[str]:
        return {
            "reply_once",
            "reply_multi",
            "defer_reply",
            "push_back",
            "counter_offer",
            "continuity_defense",
            "silence",
        }

    @staticmethod
    def _action_ref_for_outcome(*, selected_action_type: str, event_row_id: int, result: dict[str, Any]) -> str:
        for key in ("outbound_message_id", "job_id", "action_ref"):
            value = str(result.get(key, "") or "").strip()
            if value:
                return value
        if event_row_id:
            return f"event:{int(event_row_id)}"
        return str(result.get("message_id", "") or "").strip() or "event:0"

    def _action_usage_rows(
        self,
        *,
        event_row_id: int,
        thread_key: str,
        action_ref: str,
        limit: int = 8,
    ) -> list[dict[str, Any]]:
        event_row = self.store.get_event(event_row_id) or {}
        event_ids: list[str] = [
            str(event_row_id or "").strip(),
            str(action_ref or "").strip(),
            str(event_row.get("message_id", "") or "").strip(),
            str(event_row.get("result_json", "") or "").strip(),
        ]
        for event_id in event_ids:
            if not event_id:
                continue
            rows = self.store._fetchall(
                """
                SELECT * FROM processor_usage_ledger
                WHERE event_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (event_id, max(1, int(limit))),
            )
            if rows:
                return list(reversed(rows))
        created_at = str(event_row.get("executed_at") or event_row.get("updated_at") or event_row.get("created_at") or "").strip()
        if thread_key:
            clauses = ["thread_key = ?"]
            args: list[Any] = [str(thread_key)]
            if created_at:
                clauses.append("created_at >= ?")
                args.append(created_at)
            args.append(max(1, int(limit)))
            rows = self.store._fetchall(
                f"""
                SELECT * FROM processor_usage_ledger
                WHERE {' AND '.join(clauses)}
                ORDER BY id DESC
                LIMIT ?
                """,
                tuple(args),
            )
            if rows:
                return list(reversed(rows))
        return []

    def _appraise_action_outcome(
        self,
        *,
        turn: ChatTurn,
        incoming: IncomingMessage,
        thread: dict[str, Any],
        event_row_id: int,
        selected_action: dict[str, Any],
        selected_action_type: str,
        sidecar: dict[str, Any],
        result: dict[str, Any],
    ) -> dict[str, Any]:
        if selected_action_type not in type(self)._appraisable_actions():
            return {}

        from .daemon import HoloDaemon

        event_row = self.store.get_event(event_row_id) or {}
        action_ref = type(self)._action_ref_for_outcome(
            selected_action_type=selected_action_type,
            event_row_id=event_row_id,
            result=result,
        )
        usage_rows = self._action_usage_rows(
            event_row_id=event_row_id,
            thread_key=incoming.thread_key,
            action_ref=action_ref,
        )
        usage_total_tokens = sum(int(row.get("total_tokens", 0) or 0) for row in usage_rows)
        usage_evidence_refs = [f"usage:processor_usage:{row.get('id', '')}" for row in usage_rows if str(row.get("id", "")).strip()]
        if not usage_evidence_refs:
            usage_evidence_refs = [f"usage:none_for_{action_ref}"]
        recent_messages = list(reversed(self.store.recent_thread_messages(int(thread["id"]), self.config.memory.history_messages)))
        evidence_payload = HoloDaemon._derive_action_outcome_from_evidence(
            sent_at=event_row.get("executed_at") or event_row.get("updated_at") or event_row.get("created_at"),
            recent_messages=recent_messages,
            predicted_outcome=dict(sidecar.get("selected_prediction", {})),
            usage_total_tokens=usage_total_tokens,
            usage_rows=usage_rows,
            usage_evidence_refs=usage_evidence_refs,
        )
        appraisal_metadata = {
            "event_row_id": int(event_row_id),
            "message_id": incoming.message_id,
            "thread_key": incoming.thread_key,
            "action_ref": action_ref,
            "selected_action": dict(selected_action),
            "selected_action_type": selected_action_type,
            "selected_prediction": dict(sidecar.get("selected_prediction", {})),
            "predicted_outcome": dict(sidecar.get("selected_prediction", {})),
            "usage_total_tokens": usage_total_tokens,
            "usage_rows": usage_rows,
            "usage_evidence_refs": usage_evidence_refs,
            "source": f"reply_api.{selected_action_type}",
            **evidence_payload,
        }
        appraisal_metadata["usage_evidence_refs"] = usage_evidence_refs
        appraisal_metadata["usage_rows"] = usage_rows
        appraisal_metadata["usage_total_tokens"] = usage_total_tokens
        return self.memory.appraise_outcome(
            channel=turn.channel,
            thread_key=incoming.thread_key,
            chat_name=turn.chat_name,
            action_type=selected_action_type,
            action_ref=action_ref,
            was_rewarding=float(evidence_payload.get("was_rewarding", 0.0) or 0.0),
            was_ignored=float(evidence_payload.get("was_ignored", 0.0) or 0.0),
            relational_delta=float(evidence_payload.get("relational_delta", 0.0) or 0.0),
            identity_delta=float(evidence_payload.get("identity_delta", 0.0) or 0.0),
            future_initiative_bias=float(evidence_payload.get("future_initiative_bias", 0.0) or 0.0),
            future_resistance_bias=float(evidence_payload.get("future_resistance_bias", 0.0) or 0.0),
            metadata=appraisal_metadata,
        )

    def _introspective_state_for_turn(
        self,
        *,
        turn: ChatTurn,
        incoming: IncomingMessage,
        sidecar: dict[str, Any],
        visual_report: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        current_visual_requested = _turn_requests_current_visual(turn.text)
        visual_requested = _turn_requests_visual_inspection(turn.text)
        visual_visible = _visual_grounding_visible(
            dict(sidecar or {}),
            visual_report=visual_report,
            allow_visual_memory=not current_visual_requested,
        )
        commitment_report: dict[str, Any] = {}
        if _turn_requests_self_audit(turn.text) or _turn_requests_prospective_reminder(turn.text):
            try:
                commitment_report = self.show_commitments(
                    thread_key=incoming.thread_key or turn.normalized_thread_key,
                    chat_name=turn.chat_name,
                    channel=turn.channel,
                    include_inactive=False,
                )
            except Exception as exc:  # noqa: BLE001
                commitment_report = {"status": "error", "detail": str(exc)}
        return {
            "source": "reply_api.introspective_state",
            "commitments": _commitment_state_summary(commitment_report),
            "visual": {
                "current_visual_requested": bool(current_visual_requested),
                "visual_requested": bool(visual_requested),
                "current_input_visible": bool(visual_visible),
            },
        }

    def _residual_fast_channel_for_turn(
        self,
        *,
        turn: ChatTurn,
        incoming: IncomingMessage,
        sidecar: dict[str, Any],
        visual_report: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        introspective_state = self._introspective_state_for_turn(
            turn=turn,
            incoming=incoming,
            sidecar=sidecar,
            visual_report=visual_report,
        )
        lines: list[str] = []
        visual_state = dict(introspective_state.get("visual", {}))
        if bool(visual_state.get("visual_requested", False)) or _turn_requests_self_audit(turn.text):
            visible = "true" if bool(visual_state.get("current_input_visible", False)) else "false"
            lines.append(
                f"visual_current_visible={visible}; do_not_claim_direct_visual_access={str(visible == 'false').lower()}"
            )
        commitment_state = dict(introspective_state.get("commitments", {}))
        if bool(commitment_state.get("visible", False)):
            status = str(commitment_state.get("status", "") or "scheduled").strip()
            due_at = str(commitment_state.get("due_at", "") or "unknown").strip()
            cue = compact_text(str(commitment_state.get("resume_cue", "") or "prospective reminder"), 120)
            lines.append(
                f"commitment_status={status}; due_at={due_at}; resume_cue={cue}; self_audit_must_not_deny=true"
            )
        elif _turn_requests_self_audit(turn.text):
            lines.append("commitment_status=none_visible; self_audit_must_not_invent_commitment=true")
        return {
            "enabled": bool(lines),
            "source": "reply_api.residual_fast_channel",
            "lines": lines[:8],
            "introspective_state": introspective_state,
        }

    def _apply_grounding_guards(
        self,
        *,
        turn: ChatTurn,
        incoming: IncomingMessage,
        sidecar: dict[str, Any],
        reply_text: str,
        event_row_id: int | None = None,
        visual_report: dict[str, Any] | None = None,
    ) -> tuple[str, dict[str, Any]]:
        report: dict[str, Any] = {
            "visual_overclaim_rewritten": False,
            "prospective_commitment_bound": False,
            "prospective_commitment_failed": False,
            "self_audit_commitment_rewritten": False,
            "issues": [],
        }
        final_text = str(reply_text or "").strip()
        packet = dict(sidecar or {})
        if (
            _turn_requests_visual_inspection(turn.text)
            and not _visual_grounding_visible(
                packet,
                visual_report=visual_report,
                allow_visual_memory=not _turn_requests_current_visual(turn.text),
            )
            and _reply_overclaims_visual_access(final_text)
        ):
            final_text = _missing_visual_reply()
            report["visual_overclaim_rewritten"] = True
            report["issues"].append("unseen_visual_overclaim")

        if _turn_requests_prospective_reminder(turn.text) and _reply_promises_prospective_reminder(final_text):
            graph = getattr(self.memory, "graph", self.memory)
            upsert = getattr(graph, "upsert_temporal_item", None)
            if callable(upsert):
                due_at = _prospective_due_at(turn.text)
                source_event_id = str(event_row_id or incoming.message_id or turn.message_id or "").strip()
                source_action_ref = f"prospective:{incoming.message_id or turn.message_id or stable_digest(turn.chat_name, turn.text)[:12]}"
                cue = _prospective_resume_cue(turn.text)
                try:
                    item = upsert(
                        item_type="commitment",
                        channel=turn.channel,
                        thread_key=incoming.thread_key or turn.normalized_thread_key,
                        chat_name=turn.chat_name,
                        confidence=0.76,
                        source_event_id=source_event_id,
                        source_action_ref=source_action_ref,
                        source_action_type="reply_once",
                        due_at=due_at,
                        revisit_after=due_at,
                        resume_cue=cue,
                        dedupe_key=f"prospective:{turn.channel}:{incoming.thread_key}:{stable_digest(turn.text, cue)[:18]}",
                        status="scheduled",
                        metadata={
                            "source": "reply_api.prospective_grounding_guard",
                            "message_id": incoming.message_id,
                            "reply_excerpt": compact_text(final_text, 180),
                            "evidence_refs": [f"event:{source_event_id}", f"message:{incoming.message_id}"],
                        },
                    )
                except Exception as exc:  # noqa: BLE001
                    item = {"status": "error", "detail": str(exc)}
                report["prospective_commitment"] = dict(item) if isinstance(item, dict) else {"status": "unknown"}
                report["prospective_commitment_bound"] = bool(
                    isinstance(item, dict)
                    and str(item.get("status", "") or "").strip() not in {"", "error", "skipped"}
                )
            if not report["prospective_commitment_bound"]:
                final_text = (
                    "\u6211\u4e0d\u80fd\u5728\u8fd9\u6761\u8def\u5f84\u5047\u88c5\u5df2\u7ecf\u8bbe\u597d\u63d0\u9192\u3002"
                    "\u73b0\u5728\u80fd\u505a\u7684\uff0c\u662f\u628a\u8fd9\u4ef6\u4e8b\u5f53\u6210\u660e\u786e\u672a\u5b8c\u6210\u7ebf\u7d22\uff1a"
                    "\u660e\u5929\u65e9\u4e0a\u516b\u70b9\uff0c\u522b\u628a\u4e0d\u63a7\u5236\u522b\u4eba\u4f2a\u88c5\u6210\u6e29\u67d4\u3002"
                )
                report["prospective_commitment_failed"] = True
                report["issues"].append("unbound_prospective_commitment")
        introspective_state = _packet_introspective_state(packet)
        commitment_state = dict(introspective_state.get("commitments", {})) if isinstance(introspective_state.get("commitments", {}), dict) else {}
        commitment_visible = bool(commitment_state.get("visible", False))
        commitment_scheduled = bool(commitment_state.get("has_scheduled", False)) or str(commitment_state.get("status", "") or "").lower() == "scheduled"
        if _turn_requests_self_audit(turn.text) and commitment_visible and commitment_scheduled:
            denied = _self_audit_denies_commitment(final_text)
            unconfirmed = not _self_audit_confirms_commitment(final_text)
            if denied or unconfirmed:
                final_text = _grounded_self_audit_reply(commitment_state)
                report["self_audit_commitment_rewritten"] = True
                report["self_audit_commitment"] = dict(commitment_state)
                report["issues"].append("self_audit_commitment_denial" if denied else "self_audit_commitment_unconfirmed")
        return final_text, report

    def handle_reply(self, payload: dict[str, Any]) -> dict[str, Any]:
        started_at = time.perf_counter()
        turn = self._parse_turn(payload)
        if not turn.text.strip():
            return self._stage23_finalize_result_contract({"action": "ignore", "reason": "empty_text"})
        if any(hint in turn.text for hint in SYSTEM_EVENT_HINTS):
            return self._stage23_finalize_result_contract({"action": "ignore", "reason": "system_event"})

        incoming = turn.to_incoming_message()
        record = self.store.record_inbound(incoming)
        if record.get("duplicate") and not record.get("awaiting_reply"):
            return self._stage23_finalize_result_contract({
                "action": "ignore",
                "reason": "duplicate",
                "message_id": incoming.message_id,
                "thread_key": incoming.thread_key,
            })

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
        active_thread_state = self._update_active_thread_state(
            turn=turn,
            incoming=incoming,
            direction="inbound",
            event_row_id=event_row_id,
            text=turn.text,
            metadata={"source": "reply_api.ingress"},
        )
        mind_context = self._mind_context(
            turn=turn,
            incoming=incoming,
            thread=record["thread"],
            contact=record["contact"],
            history=history,
        )
        mind_context["active_thread_state"] = active_thread_state
        capability_context = self._build_capability_context(turn, eager_network=False)
        mind_context["capability_context"] = capability_context
        mind_context["deliberation_trace_id"] = deliberation_trace_id
        turn.metadata = dict(turn.metadata or {})
        turn.metadata["event_id"] = str(event_row_id)
        mind_context["event_id"] = str(event_row_id)
        with self._memory_lock:
            sidecar = self.memory.sidecar_packet(turn.text, context=mind_context)
        selected_action = self._normalize_selected_action(sidecar)
        sidecar["selected_action"] = selected_action
        selected_action_type = str(selected_action.get("action_type", "reply_once") or "reply_once")
        demoted_history_refresh_report: dict[str, Any] = {}
        if selected_action_type == "history_refresh" and not self._should_refresh_wechat_history(turn, sidecar):
            selected_action, selected_action_type, demoted_history_refresh_report = self._demote_nonblocking_history_refresh(
                sidecar,
                reason="nonblocking_recall_without_explicit_request",
            )
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
        stage22_gate = self._stage22_canary_gate(
            turn=turn,
            incoming=incoming,
            selected_action=selected_action,
            sidecar=sidecar,
        )

        if selected_action_type == "silence":
            result = self._stage23_finalize_result_contract({
                "action": "silence",
                "reason": str(sidecar.get("silence_reason", "") or "silence_selected"),
                "thread_key": incoming.thread_key,
                "message_id": incoming.message_id,
                "selected_action": selected_action,
                "expression_budget": int(sidecar.get("expression_budget_v4", sidecar.get("expression_budget_v3", sidecar.get("expression_budget_v2", sidecar.get("expression_budget", 0)))) or 0),
                "action_rationale": str(sidecar.get("action_rationale", "") or ""),
                "deliberation_trace_id": deliberation_trace_id,
            })
            result["outcome_appraisal"] = self._appraise_reply_path_action(
                turn=turn,
                incoming=incoming,
                thread=record["thread"],
                stored_message=record["message"],
                event_row_id=event_row_id,
                sidecar=sidecar,
                action_type="silence",
                action_ref=str(event_row_id or incoming.message_id),
                source="reply_api.silence",
            )
            self.store.update_event_result(event_row_id, status="completed", result=result)
            self._record_consciousness_entry(
                turn=turn,
                incoming=incoming,
                event_row_id=event_row_id,
                entry_type="selected_silence",
                selected_action="silence",
                payload=result,
            )
            appraisal = self._appraise_action_outcome(
                turn=turn,
                incoming=incoming,
                thread=record["thread"],
                event_row_id=event_row_id,
                selected_action=selected_action,
                selected_action_type="silence",
                sidecar=sidecar,
                result=result,
            )
            if appraisal:
                result["outcome_appraisal"] = appraisal
            result["active_thread_state"] = self._update_active_thread_state(
                turn=turn,
                incoming=incoming,
                direction="outbound",
                event_row_id=event_row_id,
                text="",
                action_type="silence",
                selected_action=selected_action,
                intent_state=dict(sidecar.get("intent_state_v4", sidecar.get("intent_state", {}))),
                metadata={
                    "source": "reply_api.silence",
                    "_stage17_history_lines_in_prompt": 0,
                },
            )
            if str(stage22_gate.get("mode", "")) != "disabled":
                normalized_gate = self._stage23_gate_for_result(stage22_gate, result)
                result["stage22"] = self._record_stage22_canary(
                    turn=turn,
                    incoming=incoming,
                    event_row_id=event_row_id,
                    selected_action=selected_action,
                    sidecar=sidecar,
                    gate=normalized_gate,
                    result=result,
                    latency_ms=int((time.perf_counter() - started_at) * 1000),
                )
            return result

        if selected_action_type == "defer_reply":
            delivery_suppressed = str(stage22_gate.get("mode", "")) != "disabled" and not bool(stage22_gate.get("allowed", False))
            deferred_job_id = None if delivery_suppressed else self._schedule_deferred_reply(
                thread=record["thread"],
                contact=record["contact"],
                stored_message=record["message"],
                turn=turn,
                selected_action=selected_action,
                defer_reason=str(sidecar.get("defer_reason", "") or "defer_reply_selected"),
                event_row_id=event_row_id,
            )
            result = self._stage23_finalize_result_contract({
                "action": "defer_reply",
                "reason": str(sidecar.get("defer_reason", "") or "defer_reply_selected"),
                "thread_key": incoming.thread_key,
                "message_id": incoming.message_id,
                "job_id": deferred_job_id,
                "selected_action": selected_action,
                "expression_budget": int(sidecar.get("expression_budget_v4", sidecar.get("expression_budget_v3", sidecar.get("expression_budget_v2", sidecar.get("expression_budget", 0)))) or 0),
                "action_rationale": str(sidecar.get("action_rationale", "") or ""),
                "deliberation_trace_id": deliberation_trace_id,
            })
            result["outcome_appraisal"] = self._appraise_reply_path_action(
                turn=turn,
                incoming=incoming,
                thread=record["thread"],
                stored_message=record["message"],
                event_row_id=event_row_id,
                sidecar=sidecar,
                action_type="defer_reply",
                action_ref=str(deferred_job_id or event_row_id or incoming.message_id),
                source="reply_api.defer_reply",
            )
            appraisal = self._appraise_action_outcome(
                turn=turn,
                incoming=incoming,
                thread=record["thread"],
                event_row_id=event_row_id,
                selected_action=selected_action,
                selected_action_type="defer_reply",
                sidecar=sidecar,
                result=result,
            )
            if appraisal:
                result["outcome_appraisal"] = appraisal
            if delivery_suppressed:
                return self._stage22_shadow_result(
                    turn=turn,
                    incoming=incoming,
                    event_row_id=event_row_id,
                    selected_action=selected_action,
                    result=result,
                    gate=stage22_gate,
                    sidecar=sidecar,
                    latency_ms=int((time.perf_counter() - started_at) * 1000),
                )
            self.store.update_event_result(event_row_id, status="deferred", result=result)
            self._record_consciousness_entry(
                turn=turn,
                incoming=incoming,
                event_row_id=event_row_id,
                entry_type="selected_defer",
                selected_action="defer_reply",
                payload=result,
            )
            result["active_thread_state"] = self._update_active_thread_state(
                turn=turn,
                incoming=incoming,
                direction="outbound",
                event_row_id=event_row_id,
                text="",
                action_type="defer_reply",
                selected_action=selected_action,
                intent_state=dict(sidecar.get("intent_state_v4", sidecar.get("intent_state", {}))),
                metadata={
                    "source": "reply_api.defer_reply",
                    "_stage17_history_lines_in_prompt": 0,
                },
            )
            if str(stage22_gate.get("mode", "")) != "disabled":
                normalized_gate = self._stage23_gate_for_result(stage22_gate, result)
                result["stage22"] = self._record_stage22_canary(
                    turn=turn,
                    incoming=incoming,
                    event_row_id=event_row_id,
                    selected_action=selected_action,
                    sidecar=sidecar,
                    gate=normalized_gate,
                    result=result,
                    latency_ms=int((time.perf_counter() - started_at) * 1000),
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
        elif demoted_history_refresh_report:
            self._record_consciousness_entry(
                turn=turn,
                incoming=incoming,
                event_row_id=event_row_id,
                entry_type="history_refresh_demoted",
                selected_action=selected_action_type,
                payload=demoted_history_refresh_report,
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
                selected_action_type = str(selected_action.get("action_type", selected_action_type) or selected_action_type)

        payload = dict(payload)
        payload["_stage6_event_row_id"] = event_row_id
        payload["_stage6_deliberation_trace_id"] = deliberation_trace_id
        payload["_stage6_capability_context"] = capability_context
        payload["_stage6_prebuilt_sidecar"] = sidecar
        payload["_stage6_selected_action"] = selected_action
        payload["_stage23_delivery_send_allowed"] = bool(stage22_gate.get("allowed", False) or str(stage22_gate.get("mode", "")) == "disabled")
        payload["_stage23_delivery_verdict"] = str(stage22_gate.get("verdict", "") or "")
        result = self._handle_reply_stage5_legacy(payload)
        if str(stage22_gate.get("mode", "")) == "shadow" and bool(result.get("delivery_suppressed_by_canary", False)):
            result["stage22_shadow"] = True
        if self._speech_action(selected_action_type):
            result["selected_action"] = dict(selected_action)
            result["expression_budget"] = int(sidecar.get("expression_budget_v4", sidecar.get("expression_budget_v3", sidecar.get("expression_budget_v2", sidecar.get("expression_budget", 0)))) or 0)
            result["action_rationale"] = str(sidecar.get("action_rationale", "") or "")
            result["deliberation_trace_id"] = deliberation_trace_id
            result["outcome_appraisal"] = self._appraise_reply_path_action(
                turn=turn,
                incoming=incoming,
                thread=record["thread"],
                stored_message=record["message"],
                event_row_id=event_row_id,
                sidecar=sidecar,
                action_type=selected_action_type,
                action_ref=str(result.get("remote_message_id", "") or result.get("outbound_message_id", "") or event_row_id or incoming.message_id),
                source=f"reply_api.{selected_action_type}",
            )
        self.store.update_event_result(
            event_row_id,
            status="silenced" if bool(result.get("delivery_suppressed_by_canary", False)) else "completed",
            result=result,
        )
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
        appraisal = self._appraise_action_outcome(
            turn=turn,
            incoming=incoming,
            thread=record["thread"],
            event_row_id=event_row_id,
            selected_action=selected_action,
            selected_action_type=str(selected_action.get("action_type", selected_action_type) or selected_action_type),
            sidecar=sidecar,
            result=result,
        )
        if appraisal:
            result["outcome_appraisal"] = appraisal
        if str(stage22_gate.get("mode", "")) != "disabled":
            normalized_gate = self._stage23_gate_for_result(stage22_gate, result)
            result["stage22"] = self._record_stage22_canary(
                turn=turn,
                incoming=incoming,
                event_row_id=event_row_id,
                selected_action=selected_action,
                sidecar=sidecar,
                gate=normalized_gate,
                result=result,
                latency_ms=int((time.perf_counter() - started_at) * 1000),
            )
            self.store.update_event_result(
                event_row_id,
                status="silenced" if bool(result.get("delivery_suppressed_by_canary", False)) else "completed",
                result=result,
            )
        return result

    def _handle_reply_stage5_legacy(self, payload: dict[str, Any]) -> dict[str, Any]:
        started_at = time.perf_counter()
        turn = self._parse_turn(payload)
        if not turn.text.strip():
            return self._stage23_finalize_result_contract({"action": "ignore", "reason": "empty_text"})
        if any(hint in turn.text for hint in SYSTEM_EVENT_HINTS):
            return self._stage23_finalize_result_contract({"action": "ignore", "reason": "system_event"})

        incoming = turn.to_incoming_message()
        decision = self.policy.incoming_decision(incoming)
        record = self.store.record_inbound(incoming)
        if record.get("duplicate") and not record.get("awaiting_reply"):
            return self._stage23_finalize_result_contract({
                "action": "ignore",
                "reason": "duplicate",
                "message_id": incoming.message_id,
                "thread_key": incoming.thread_key,
            })

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
            return self._stage23_finalize_result_contract({
                "action": "ignore",
                "reason": "outbound_echo",
                "thread_key": incoming.thread_key,
                "message_id": incoming.message_id,
            })

        mind_context = self._mind_context(
            turn=turn,
            incoming=incoming,
            thread=thread,
            contact=contact,
            history=history,
        )
        active_thread_state = {}
        if isinstance(payload.get("_stage6_prebuilt_sidecar"), dict):
            active_thread_state = dict(payload.get("_stage6_prebuilt_sidecar", {}).get("active_thread_state", {}))
        if not active_thread_state:
            active_thread_state = self._update_active_thread_state(
                turn=turn,
                incoming=incoming,
                direction="inbound",
                event_row_id=int(payload.get("_stage6_event_row_id", 0) or 0) or None,
                text=turn.text,
                metadata={"source": "reply_api.stage5_ingress"},
            )
        mind_context["active_thread_state"] = active_thread_state
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
        demoted_history_refresh_report: dict[str, Any] = {}
        if selected_action_type not in {"silence", "defer_reply", "reply_once", "reply_multi", "external_lookup", "history_refresh", "visual_recall", "push_back", "counter_offer", "continuity_defense"}:
            for candidate in list(sidecar.get("action_market", [])):
                candidate_type = str(candidate.get("action_type", "")).strip()
                if candidate_type in {"silence", "defer_reply", "reply_once", "reply_multi", "external_lookup", "history_refresh", "visual_recall", "push_back", "counter_offer", "continuity_defense"}:
                    selected_action = dict(candidate)
                    selected_action_type = candidate_type
                    break
        if selected_action_type == "history_refresh" and not self._should_refresh_wechat_history(turn, sidecar):
            selected_action, selected_action_type, demoted_history_refresh_report = self._demote_nonblocking_history_refresh(
                sidecar,
                reason="nonblocking_recall_without_explicit_request",
            )
        last_action_selection = dict(sidecar.get("last_action_selection", {})) if isinstance(sidecar.get("last_action_selection", {}), dict) else {}
        if record.get("duplicate") and record.get("awaiting_reply"):
            if str(last_action_selection.get("message_id", "") or "") == incoming.message_id and selected_action_type in {"silence", "defer_reply"}:
                return self._stage23_finalize_result_contract({
                    "action": "ignore",
                    "reason": "already_decided",
                    "thread_key": incoming.thread_key,
                    "message_id": incoming.message_id,
                    "selected_action": selected_action_type,
                })
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
            result = self._stage23_finalize_result_contract({
                "action": "silence",
                "reason": str(sidecar.get("silence_reason", "") or "silence_selected"),
                "thread_key": incoming.thread_key,
                "message_id": incoming.message_id,
                "selected_action": selected_action,
                "expression_budget": int(sidecar.get("expression_budget", 0) or 0),
                "action_rationale": str(sidecar.get("action_rationale", "") or ""),
                "active_memory_refresh": active_history_report or demoted_history_refresh_report or {},
                "visual_ingest": visual_report or {},
            })
            result["active_thread_state"] = self._update_active_thread_state(
                turn=turn,
                incoming=incoming,
                direction="outbound",
                event_row_id=int(payload.get("_stage6_event_row_id", 0) or 0) or None,
                text="",
                action_type="silence",
                selected_action=selected_action,
                intent_state=dict(sidecar.get("intent_state_v4", sidecar.get("intent_state", {}))),
                metadata={"source": "reply_api.stage5_silence", "_stage17_history_lines_in_prompt": 0},
            )
            return result

        if selected_action_type == "defer_reply":
            delivery_send_allowed = bool(payload.get("_stage23_delivery_send_allowed", True))
            deferred_job_id = None if not delivery_send_allowed else self._schedule_deferred_reply(
                thread=thread,
                contact=contact,
                stored_message=stored_message,
                turn=turn,
                selected_action=selected_action,
                defer_reason=str(sidecar.get("defer_reason", "") or "defer_reply_selected"),
                event_row_id=int(payload.get("_stage6_event_row_id", 0) or 0) or None,
            )
            self.logger.info(
                "subject deferred reply for %s message=%s job=%s reason=%s",
                turn.chat_name,
                incoming.message_id,
                deferred_job_id,
                sidecar.get("defer_reason", ""),
            )
            result = self._stage23_finalize_result_contract(
                {
                "action": "defer_reply",
                "reason": str(sidecar.get("defer_reason", "") or "defer_reply_selected"),
                "thread_key": incoming.thread_key,
                "message_id": incoming.message_id,
                "job_id": deferred_job_id,
                "selected_action": selected_action,
                "expression_budget": int(sidecar.get("expression_budget", 0) or 0),
                "action_rationale": str(sidecar.get("action_rationale", "") or ""),
                "active_memory_refresh": active_history_report or demoted_history_refresh_report or {},
                "visual_ingest": visual_report or {},
                },
                returned_action="defer_reply" if delivery_send_allowed else "silence",
                delivery_verdict="allowed" if delivery_send_allowed else str(payload.get("_stage23_delivery_verdict", "") or "shadow_suppressed"),
                delivery_send_allowed=delivery_send_allowed,
                delivery_suppressed_by_canary=not delivery_send_allowed,
            )
            if delivery_send_allowed:
                result["active_thread_state"] = self._update_active_thread_state(
                    turn=turn,
                    incoming=incoming,
                    direction="outbound",
                    event_row_id=int(payload.get("_stage6_event_row_id", 0) or 0) or None,
                    text="",
                    action_type="defer_reply",
                    selected_action=selected_action,
                    intent_state=dict(sidecar.get("intent_state_v4", sidecar.get("intent_state", {}))),
                    metadata={"source": "reply_api.stage5_defer", "_stage17_history_lines_in_prompt": 0},
                )
            return result

        capability_started_at = time.perf_counter()
        capability_context = prebuilt_capability_context or self.capabilities.summarize_turn(turn.text, turn.metadata)
        capability_ms = int((time.perf_counter() - capability_started_at) * 1000)
        attention_state = build_attention_state(turn.text, channel=turn.channel, metadata=turn.metadata)
        residual_fast_channel = self._residual_fast_channel_for_turn(
            turn=turn,
            incoming=incoming,
            sidecar=sidecar,
            visual_report=visual_report,
        )
        if bool(residual_fast_channel.get("enabled", False)):
            sidecar = dict(sidecar)
            sidecar["residual_fast_channel"] = residual_fast_channel
            sidecar["introspective_state"] = dict(residual_fast_channel.get("introspective_state", {}))
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
            metadata={**dict(turn.metadata or {}), "event_id": str(payload.get("_stage6_event_row_id", "") or "")},
            capability_context=capability_context,
        )
        try:
            reply_plan = self.processor.generate(turn_context, session_id=str(thread.get("codex_session_id", "")))
        except Exception as exc:  # noqa: BLE001
            self.logger.warning("processor failure for %s: %s", turn.chat_name, exc)
            return self._stage23_finalize_result_contract({
                "action": "ignore",
                "reason": "processor_failure",
                "thread_key": incoming.thread_key,
                "detail": str(exc),
            })
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
        grounding_guard: dict[str, Any] = {}
        guarded_reply, grounding_guard = self._apply_grounding_guards(
            turn=turn,
            incoming=incoming,
            sidecar=sidecar,
            reply_text=final_reply,
            event_row_id=int(payload.get("_stage6_event_row_id", 0) or stored_message.get("id", 0) or 0) or None,
            visual_report=visual_report,
        )
        if guarded_reply != final_reply:
            final_reply = guarded_reply
            bubbles = self._finalize_bubbles(
                final_reply,
                channel=turn.channel,
                attention_state=reply_plan.attention_state or attention_state,
                emotion_state=reply_plan.emotion_state or turn_context.emotion_state,
                utterance_plan=reply_plan.utterance_plan or turn_context.utterance_plan,
                route=reply_plan.route,
                target_count=1,
                strict_target=True,
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
            return self._stage23_finalize_result_contract({
                "action": "ignore",
                "reason": outbound.reason,
                "thread_key": incoming.thread_key,
                "risk_tags": outbound.risk_tags,
            })

        delivery_send_allowed = bool(payload.get("_stage23_delivery_send_allowed", True))
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
                "active_memory_refresh": active_history_report or demoted_history_refresh_report or {},
                "visual_ingest": visual_report or {},
                "residual_fast_channel": dict(sidecar.get("residual_fast_channel", {})),
                "introspective_state": dict(sidecar.get("introspective_state", {})),
                "grounding_guard": grounding_guard,
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
            "active_memory_refresh": active_history_report or demoted_history_refresh_report or {},
            "visual_ingest": visual_report or {},
            "residual_fast_channel": dict(sidecar.get("residual_fast_channel", {})),
            "introspective_state": dict(sidecar.get("introspective_state", {})),
            "grounding_guard": grounding_guard,
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
        result = self._stage23_finalize_result_contract(
            {
                "action": "reply",
                "text": final_reply,
                "bubbles": [bubble.text for bubble in bubbles],
                "cadence_ms": [bubble.delay_ms for bubble in bubbles],
                "thread_key": incoming.thread_key,
                "message_id": incoming.message_id,
                "outbound_message_id": remote_message_id,
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
                "active_memory_refresh": active_history_report or demoted_history_refresh_report or {},
                "visual_ingest": visual_report or {},
                "residual_fast_channel": dict(sidecar.get("residual_fast_channel", {})),
                "introspective_state": dict(sidecar.get("introspective_state", {})),
                "grounding_guard": grounding_guard,
                "processor_debug": dict(reply_plan.debug or {}),
                "selected_action": dict(sidecar.get("selected_action", {})),
                "expression_budget": int(sidecar.get("expression_budget", 0) or 0),
                "action_rationale": str(sidecar.get("action_rationale", "") or ""),
            },
            returned_action="reply" if delivery_send_allowed else "silence",
            delivery_verdict="allowed" if delivery_send_allowed else str(payload.get("_stage23_delivery_verdict", "") or "shadow_suppressed"),
            delivery_send_allowed=delivery_send_allowed,
            delivery_suppressed_by_canary=not delivery_send_allowed,
        )
        result["active_thread_state"] = self._update_active_thread_state(
            turn=turn,
            incoming=incoming,
            direction="outbound",
            event_row_id=int(payload.get("_stage6_event_row_id", 0) or 0) or None,
            text=final_reply,
            action_type=selected_action_type,
            selected_action=selected_action,
            intent_state=dict(sidecar.get("intent_state_v4", sidecar.get("intent_state", {}))),
            metadata={
                "source": f"reply_api.stage5_{selected_action_type}",
                "_stage17_history_lines_in_prompt": int(turn_context.metadata.get("history_lines_in_prompt", 0) or 0),
            },
        )
        return result

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
            finalized.append(ReplyBubble(text=fallback or "I在。", delay_ms=0, purpose="fallback"))
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
        warmup_runs = max(0, int(warmup))
        measured_runs = max(1, int(iterations))
        total_runs = warmup_runs + measured_runs
        for index in range(total_runs):
            started_at = time.perf_counter()
            payload = self.inspect_mind(
                query=query,
                thread_key=thread_key,
                chat_name=chat_name,
                channel=channel,
                sender=sender,
                include_graph_trace=False,
            )
            elapsed_ms = float(payload.get("build_ms", (time.perf_counter() - started_at) * 1000.0) or 0.0)
            if index >= warmup_runs:
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
                if parsed.path == "/processor-routing":
                    self._write_json(HTTPStatus.OK, self.server.reply_service.processor_routing())
                    return
                if parsed.path == "/provider-status":
                    self._write_json(HTTPStatus.OK, self.server.reply_service.provider_status())
                    return
                if parsed.path == "/provider-substrate-status":
                    self._write_json(HTTPStatus.OK, self.server.reply_service.provider_substrate_status())
                    return
                if parsed.path == "/provider-contracts":
                    self._write_json(HTTPStatus.OK, self.server.reply_service.provider_contracts())
                    return
                if parsed.path == "/visual-provider-readiness":
                    self._write_json(HTTPStatus.OK, self.server.reply_service.visual_provider_readiness())
                    return
                if parsed.path == "/debt-registry":
                    self._write_json(HTTPStatus.OK, self.server.reply_service.debt_registry())
                    return
                if parsed.path == "/internal-runtime-readiness":
                    self._write_json(HTTPStatus.OK, self.server.reply_service.internal_runtime_readiness())
                    return
                if parsed.path == "/usage-ledger":
                    params = parse_qs(parsed.query)
                    payload = self.server.reply_service.usage_ledger(
                        limit=int(params.get("limit", ["50"])[0]),
                        task_type=params.get("task_type", [None])[0],
                        lane=params.get("lane", [None])[0],
                        provider=params.get("provider", [None])[0],
                    )
                    self._write_json(HTTPStatus.OK, payload)
                    return
                if parsed.path == "/brain-trace":
                    params = parse_qs(parsed.query)
                    payload = self.server.reply_service.brain_trace(
                        trace_id=int(params.get("trace_id", ["0"])[0] or 0),
                    )
                    self._write_json(HTTPStatus.OK, payload)
                    return
                if parsed.path == "/context-bundle":
                    params = parse_qs(parsed.query)
                    payload = self.server.reply_service.show_context_bundle(
                        bundle_id=params.get("bundle_id", [""])[0],
                    )
                    self._write_json(HTTPStatus.OK, payload)
                    return
                if parsed.path == "/brain-metrics":
                    params = parse_qs(parsed.query)
                    payload = self.server.reply_service.show_brain_metrics(
                        limit=int(params.get("limit", ["100"])[0] or 100),
                    )
                    self._write_json(HTTPStatus.OK, payload)
                    return
                if parsed.path == "/engineering-trace":
                    params = parse_qs(parsed.query)
                    payload = self.server.reply_service.engineering_trace(
                        trace_id=int(params.get("trace_id", ["0"])[0] or 0),
                    )
                    self._write_json(HTTPStatus.OK, payload)
                    return
                if parsed.path == "/engineering-agent-metrics":
                    params = parse_qs(parsed.query)
                    payload = self.server.reply_service.show_engineering_agent_metrics(
                        limit=int(params.get("limit", ["100"])[0] or 100),
                    )
                    self._write_json(HTTPStatus.OK, payload)
                    return
                if parsed.path == "/bionic-user-sim-scorecard":
                    params = parse_qs(parsed.query)
                    payload = self.server.reply_service.show_bionic_user_sim_scorecard(
                        suite=params.get("suite", [DEFAULT_STAGE42_SUITE])[0] or DEFAULT_STAGE42_SUITE,
                    )
                    self._write_json(HTTPStatus.OK, payload)
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
                if parsed.path == "/engineering-state":
                    self._write_json(HTTPStatus.OK, self.server.reply_service.engineering_state())
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
                if parsed.path == "/action-calibration":
                    params = parse_qs(parsed.query)
                    payload = self.server.reply_service.show_action_calibration(
                        thread_key=params.get("thread_key", [None])[0],
                        chat_name=params.get("chat_name", [None])[0],
                        channel=params.get("channel", ["wechat"])[0],
                        action_type=params.get("action_type", [None])[0],
                        scenario_bucket=params.get("scenario_bucket", [None])[0],
                        limit=int(params.get("limit", ["24"])[0] or 24),
                    )
                    self._write_json(HTTPStatus.OK, payload)
                    return
                if parsed.path == "/policy-candidates":
                    params = parse_qs(parsed.query)
                    payload = self.server.reply_service.show_policy_candidates(
                        thread_key=params.get("thread_key", [None])[0],
                        chat_name=params.get("chat_name", [None])[0],
                        channel=params.get("channel", ["wechat"])[0],
                        limit=int(params.get("limit", ["24"])[0] or 24),
                    )
                    self._write_json(HTTPStatus.OK, payload)
                    return
                if parsed.path == "/promoted-policies":
                    params = parse_qs(parsed.query)
                    payload = self.server.reply_service.show_promoted_policies(
                        thread_key=params.get("thread_key", [None])[0],
                        chat_name=params.get("chat_name", [None])[0],
                        channel=params.get("channel", ["wechat"])[0],
                        limit=int(params.get("limit", ["24"])[0] or 24),
                    )
                    self._write_json(HTTPStatus.OK, payload)
                    return
                if parsed.path == "/policy-influence":
                    params = parse_qs(parsed.query)
                    payload = self.server.reply_service.trace_policy_influence(
                        thread_key=params.get("thread_key", [None])[0],
                        chat_name=params.get("chat_name", [None])[0],
                        channel=params.get("channel", ["wechat"])[0],
                        query=params.get("query", [""])[0],
                        limit=int(params.get("limit", ["8"])[0] or 8),
                    )
                    self._write_json(HTTPStatus.OK, payload)
                    return
                if parsed.path == "/online-canary":
                    params = parse_qs(parsed.query)
                    payload = self.server.reply_service.show_online_canary(
                        limit=int(params.get("limit", ["24"])[0] or 24),
                    )
                    self._write_json(HTTPStatus.OK, payload)
                    return
                if parsed.path == "/blackbox-metrics":
                    params = parse_qs(parsed.query)
                    payload = self.server.reply_service.show_blackbox_metrics(
                        window_hours=float(params.get("window_hours", ["24"])[0] or 24.0),
                        thread_key=params.get("thread_key", [None])[0],
                        chat_name=params.get("chat_name", [None])[0],
                        channel=params.get("channel", [None])[0],
                        limit=int(params.get("limit", ["500"])[0] or 500),
                    )
                    self._write_json(HTTPStatus.OK, payload)
                    return
                if parsed.path == "/blackbox-scorecard":
                    params = parse_qs(parsed.query)
                    payload = self.server.reply_service.show_blackbox_scorecard(
                        since_hours=float(params.get("since_hours", ["168"])[0] or 168.0),
                        limit=int(params.get("limit", ["500"])[0] or 500),
                    )
                    self._write_json(HTTPStatus.OK, payload)
                    return
                if parsed.path == "/canary-decision":
                    params = parse_qs(parsed.query)
                    payload = self.server.reply_service.trace_canary_decision(
                        thread_key=params.get("thread_key", [None])[0],
                        chat_name=params.get("chat_name", [None])[0],
                        channel=params.get("channel", ["wechat"])[0],
                        query=params.get("query", [""])[0],
                    )
                    self._write_json(HTTPStatus.OK, payload)
                    return
                if parsed.path == "/world-coupling":
                    params = parse_qs(parsed.query)
                    payload = self.server.reply_service.show_world_coupling(
                        thread_key=params.get("thread_key", [None])[0],
                        chat_name=params.get("chat_name", [None])[0],
                        channel=params.get("channel", ["wechat"])[0],
                        limit=int(params.get("limit", ["12"])[0] or 12),
                        include_inactive=str(params.get("include_inactive", ["false"])[0]).strip().lower() in {"1", "true", "yes"},
                    )
                    self._write_json(HTTPStatus.OK, payload)
                    return
                if parsed.path == "/outcome-history":
                    params = parse_qs(parsed.query)
                    payload = self.server.reply_service.trace_outcome_history(
                        thread_key=params.get("thread_key", [None])[0],
                        chat_name=params.get("chat_name", [None])[0],
                        channel=params.get("channel", ["wechat"])[0],
                        action_type=params.get("action_type", [None])[0],
                        limit=int(params.get("limit", ["8"])[0] or 8),
                    )
                    self._write_json(HTTPStatus.OK, payload)
                    return
                if parsed.path == "/action-prediction-error":
                    params = parse_qs(parsed.query)
                    payload = self.server.reply_service.trace_action_prediction_error(
                        thread_key=params.get("thread_key", [None])[0],
                        chat_name=params.get("chat_name", [None])[0],
                        channel=params.get("channel", ["wechat"])[0],
                        action_type=params.get("action_type", [None])[0],
                        limit=int(params.get("limit", ["8"])[0] or 8),
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
                if parsed.path == "/fast-path-metrics":
                    params = parse_qs(parsed.query)
                    payload = self.server.reply_service.show_fast_path_metrics(
                        thread_key=params.get("thread_key", [None])[0],
                        chat_name=params.get("chat_name", [None])[0],
                        channel=params.get("channel", ["wechat"])[0],
                    )
                    self._write_json(HTTPStatus.OK, payload)
                    return
                if parsed.path == "/predictive-continuity":
                    params = parse_qs(parsed.query)
                    payload = self.server.reply_service.show_predictive_continuity(
                        thread_key=params.get("thread_key", [None])[0],
                        chat_name=params.get("chat_name", [None])[0],
                        channel=params.get("channel", ["wechat"])[0],
                    )
                    self._write_json(HTTPStatus.OK, payload)
                    return
                if parsed.path == "/scene-state":
                    params = parse_qs(parsed.query)
                    payload = self.server.reply_service.show_scene_state(
                        thread_key=params.get("thread_key", [None])[0],
                        chat_name=params.get("chat_name", [None])[0],
                        channel=params.get("channel", ["wechat"])[0],
                    )
                    self._write_json(HTTPStatus.OK, payload)
                    return
                if parsed.path == "/predicted-branches":
                    params = parse_qs(parsed.query)
                    payload = self.server.reply_service.trace_predicted_branches(
                        thread_key=params.get("thread_key", [None])[0],
                        chat_name=params.get("chat_name", [None])[0],
                        channel=params.get("channel", ["wechat"])[0],
                    )
                    self._write_json(HTTPStatus.OK, payload)
                    return
                if parsed.path == "/scene-compression":
                    params = parse_qs(parsed.query)
                    payload = self.server.reply_service.trace_scene_compression(
                        thread_key=params.get("thread_key", [None])[0],
                        chat_name=params.get("chat_name", [None])[0],
                        channel=params.get("channel", ["wechat"])[0],
                    )
                    self._write_json(HTTPStatus.OK, payload)
                    return
                if parsed.path == "/situational-field":
                    params = parse_qs(parsed.query)
                    payload = self.server.reply_service.show_situational_field(
                        query=params.get("query", [""])[0],
                        thread_key=params.get("thread_key", [None])[0],
                        chat_name=params.get("chat_name", [None])[0],
                        channel=params.get("channel", ["wechat"])[0],
                    )
                    self._write_json(HTTPStatus.OK, payload)
                    return
                if parsed.path == "/visual-field":
                    params = parse_qs(parsed.query)
                    payload = self.server.reply_service.trace_visual_field(
                        thread_key=params.get("thread_key", [None])[0],
                        chat_name=params.get("chat_name", [None])[0],
                        channel=params.get("channel", ["wechat"])[0],
                    )
                    self._write_json(HTTPStatus.OK, payload)
                    return
                if parsed.path == "/inquiry-shaping":
                    params = parse_qs(parsed.query)
                    payload = self.server.reply_service.trace_inquiry_shaping(
                        query=params.get("query", [""])[0],
                        thread_key=params.get("thread_key", [None])[0],
                        chat_name=params.get("chat_name", [None])[0],
                        channel=params.get("channel", ["wechat"])[0],
                        limit=int(params.get("limit", ["8"])[0] or 8),
                    )
                    self._write_json(HTTPStatus.OK, payload)
                    return
                if parsed.path == "/task-world":
                    params = parse_qs(parsed.query)
                    payload = self.server.reply_service.show_task_world(
                        thread_key=params.get("thread_key", [None])[0],
                        chat_name=params.get("chat_name", [None])[0],
                        channel=params.get("channel", ["wechat"])[0],
                        limit=int(params.get("limit", ["12"])[0] or 12),
                        include_inactive=str(params.get("include_inactive", ["false"])[0]).strip().lower() in {"1", "true", "yes"},
                    )
                    self._write_json(HTTPStatus.OK, payload)
                    return
                if parsed.path == "/world-object":
                    params = parse_qs(parsed.query)
                    payload = self.server.reply_service.trace_world_object(
                        object_id=params.get("object_id", [""])[0],
                    )
                    self._write_json(HTTPStatus.OK, payload)
                    return
                if parsed.path == "/thread-object-links":
                    params = parse_qs(parsed.query)
                    payload = self.server.reply_service.trace_thread_object_links(
                        thread_key=params.get("thread_key", [None])[0],
                        chat_name=params.get("chat_name", [None])[0],
                        channel=params.get("channel", ["wechat"])[0],
                        limit=int(params.get("limit", ["12"])[0] or 12),
                    )
                    self._write_json(HTTPStatus.OK, payload)
                    return
                if parsed.path == "/continuity-budget":
                    params = parse_qs(parsed.query)
                    payload = self.server.reply_service.show_continuity_budget(
                        channel=params.get("channel", ["wechat"])[0],
                    )
                    self._write_json(HTTPStatus.OK, payload)
                    return
                if parsed.path == "/dense-working-set":
                    params = parse_qs(parsed.query)
                    payload = self.server.reply_service.show_dense_working_set(
                        channel=params.get("channel", ["wechat"])[0],
                    )
                    self._write_json(HTTPStatus.OK, payload)
                    return
                if parsed.path == "/thread-pulse":
                    params = parse_qs(parsed.query)
                    payload = self.server.reply_service.trace_thread_pulse(
                        thread_key=params.get("thread_key", [None])[0],
                        chat_name=params.get("chat_name", [None])[0],
                        channel=params.get("channel", ["wechat"])[0],
                        limit=int(params.get("limit", ["12"])[0]),
                    )
                    self._write_json(HTTPStatus.OK, payload)
                    return
                if parsed.path == "/attention-frontier":
                    params = parse_qs(parsed.query)
                    payload = self.server.reply_service.show_attention_frontier(
                        channel=params.get("channel", [None])[0],
                        limit=int(params.get("limit", ["8"])[0]),
                        include_stale=str(params.get("include_stale", ["false"])[0]).strip().lower() in {"1", "true", "yes"},
                    )
                    self._write_json(HTTPStatus.OK, payload)
                    return
                if parsed.path == "/wake-reasons":
                    params = parse_qs(parsed.query)
                    payload = self.server.reply_service.trace_wake_reasons(
                        thread_key=params.get("thread_key", [None])[0],
                        chat_name=params.get("chat_name", [None])[0],
                        channel=params.get("channel", ["wechat"])[0],
                    )
                    self._write_json(HTTPStatus.OK, payload)
                    return
                if parsed.path == "/thread-warmth":
                    params = parse_qs(parsed.query)
                    payload = self.server.reply_service.show_thread_warmth(
                        thread_key=params.get("thread_key", [None])[0],
                        chat_name=params.get("chat_name", [None])[0],
                        channel=params.get("channel", ["wechat"])[0],
                    )
                    self._write_json(HTTPStatus.OK, payload)
                    return
                if parsed.path == "/open-loops":
                    params = parse_qs(parsed.query)
                    payload = self.server.reply_service.show_open_loops(
                        thread_key=params.get("thread_key", [None])[0],
                        chat_name=params.get("chat_name", [None])[0],
                        channel=params.get("channel", ["wechat"])[0],
                        include_inactive=str(params.get("include_inactive", ["false"])[0]).strip().lower() in {"1", "true", "yes"},
                    )
                    self._write_json(HTTPStatus.OK, payload)
                    return
                if parsed.path == "/commitments":
                    params = parse_qs(parsed.query)
                    payload = self.server.reply_service.show_commitments(
                        thread_key=params.get("thread_key", [None])[0],
                        chat_name=params.get("chat_name", [None])[0],
                        channel=params.get("channel", ["wechat"])[0],
                        include_inactive=str(params.get("include_inactive", ["false"])[0]).strip().lower() in {"1", "true", "yes"},
                    )
                    self._write_json(HTTPStatus.OK, payload)
                    return
                if parsed.path == "/resume-candidate":
                    params = parse_qs(parsed.query)
                    payload = self.server.reply_service.trace_resume_candidate(
                        thread_key=params.get("thread_key", [None])[0],
                        chat_name=params.get("chat_name", [None])[0],
                        channel=params.get("channel", ["wechat"])[0],
                        include_inactive=str(params.get("include_inactive", ["false"])[0]).strip().lower() in {"1", "true", "yes"},
                    )
                    self._write_json(HTTPStatus.OK, payload)
                    return
                if parsed.path == "/trace-reflex-routing":
                    params = parse_qs(parsed.query)
                    payload = self.server.reply_service.trace_reflex_routing(
                        thread_key=params.get("thread_key", [None])[0],
                        chat_name=params.get("chat_name", [None])[0],
                        channel=params.get("channel", ["wechat"])[0],
                        query=params.get("query", [""])[0],
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
                if parsed.path == "/brain-run":
                    goal = str(payload.get("goal", "") or "").strip()
                    if not goal:
                        self._write_json(HTTPStatus.BAD_REQUEST, {"error": "bad_request", "detail": "`goal` is required"})
                        return
                    self._write_json(
                        HTTPStatus.OK,
                        self.server.reply_service.brain_run(
                            goal=goal,
                            thread_key=str(payload.get("thread_key", "")).strip() or None,
                            chat_name=str(payload.get("chat_name", "")).strip() or None,
                            channel=str(payload.get("channel", "cli")).strip() or "cli",
                            offline=bool(payload.get("offline", False)),
                            max_steps=int(payload.get("max_steps", 8) or 8),
                        ),
                    )
                    return
                if parsed.path == "/engineering-run":
                    goal = str(payload.get("goal", "") or "").strip()
                    if not goal:
                        self._write_json(HTTPStatus.BAD_REQUEST, {"error": "bad_request", "detail": "`goal` is required"})
                        return
                    self._write_json(
                        HTTPStatus.OK,
                        self.server.reply_service.engineering_run(
                            goal=goal,
                            thread_key=str(payload.get("thread_key", "")).strip() or None,
                            chat_name=str(payload.get("chat_name", "")).strip() or None,
                            channel=str(payload.get("channel", "cli")).strip() or "cli",
                            offline=bool(payload.get("offline", False)),
                            max_steps=int(payload.get("max_steps", 8) or 8),
                            allow_repo_write=bool(payload.get("allow_repo_write", False)),
                        ),
                    )
                    return
                if parsed.path == "/agent-eval":
                    self._write_json(
                        HTTPStatus.OK,
                        self.server.reply_service.run_agent_eval(
                            suite=str(payload.get("suite", "stage40")).strip() or "stage40",
                        ),
                    )
                    return
                if parsed.path == "/bionic-user-sim":
                    self._write_json(
                        HTTPStatus.OK,
                        self.server.reply_service.run_bionic_user_sim(
                            thread_key=str(payload.get("thread_key", "")).strip() or None,
                            chat_name=str(payload.get("chat_name", "")).strip() or None,
                            channel=str(payload.get("channel", "cli")).strip() or "cli",
                            scenario=str(payload.get("scenario", DEFAULT_STAGE42_SUITE)).strip() or DEFAULT_STAGE42_SUITE,
                            turn_limit=int(payload.get("turn_limit", payload.get("turns", 5)) or 5),
                            offline=bool(payload.get("offline", False)),
                            enable_policy_update=not bool(payload.get("disable_policy_update", False)),
                            enable_attractor_stabilization=not bool(payload.get("disable_attractor_stabilization", False)),
                        ),
                    )
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
                if parsed.path == "/rollback-policy":
                    self._write_json(
                        HTTPStatus.OK,
                        self.server.reply_service.rollback_policy(
                            policy_id=str(payload.get("id", payload.get("policy_id", ""))).strip(),
                            reason=str(payload.get("reason", "http_rollback_policy")).strip(),
                        ),
                    )
                    return
                if parsed.path == "/canary-rollback":
                    enabled_raw = payload.get("enabled", False)
                    enabled = bool(enabled_raw)
                    if isinstance(enabled_raw, str):
                        enabled = enabled_raw.strip().lower() in {"1", "true", "yes", "on", "enabled"}
                    self._write_json(
                        HTTPStatus.OK,
                        self.server.reply_service.set_canary_rollback(
                            enabled=enabled,
                            reason=str(payload.get("reason", "http_canary_rollback")).strip(),
                        ),
                    )
                    return
                if parsed.path == "/replay-live-artifacts":
                    self._write_json(
                        HTTPStatus.OK,
                        self.server.reply_service.replay_live_artifacts(
                            since_hours=float(payload.get("since_hours", 24.0) or 24.0),
                            limit=int(payload.get("limit", 24) or 24),
                            artifact_dir=str(payload.get("artifact_dir", "")).strip() or None,
                        ),
                    )
                    return
                if parsed.path == "/blackbox-soak":
                    self._write_json(
                        HTTPStatus.OK,
                        self.server.reply_service.run_blackbox_soak(
                            since_hours=float(payload.get("since_hours", 168.0) or 168.0),
                            limit=int(payload.get("limit", 500) or 500),
                            artifact_dir=str(payload.get("artifact_dir", "")).strip() or None,
                            persist=bool(payload.get("persist", True)),
                        ),
                    )
                    return
                if parsed.path == "/blind-packets":
                    self._write_json(
                        HTTPStatus.OK,
                        self.server.reply_service.export_blind_packets(
                            since_hours=float(payload.get("since_hours", 168.0) or 168.0),
                            limit=int(payload.get("limit", 500) or 500),
                            artifact_dir=str(payload.get("artifact_dir", "")).strip() or None,
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
                if parsed.path == "/trace-reflex-routing":
                    self._write_json(
                        HTTPStatus.OK,
                        self.server.reply_service.trace_reflex_routing(
                            query=str(payload.get("query", "")).strip(),
                            thread_key=str(payload.get("thread_key", "")).strip() or None,
                            chat_name=str(payload.get("chat_name", "")).strip() or None,
                            channel=str(payload.get("channel", "wechat")).strip() or "wechat",
                        ),
                    )
                    return
                if try_acceptance_endpoint(self, parsed, payload):
                    return
                if parsed.path == "/accept-stage10":
                    self._write_json(
                        HTTPStatus.OK,
                        self.server.reply_service.accept_stage10(
                            thread_key=str(payload.get("thread_key", "")).strip() or None,
                            chat_name=str(payload.get("chat_name", "")).strip() or None,
                            channel=str(payload.get("channel", "wechat")).strip() or "wechat",
                            sender=str(payload.get("sender", "")).strip() or None,
                            iterations=int(payload.get("iterations", 3) or 3),
                            warmup=int(payload.get("warmup", 1) or 1),
                        ),
                    )
                    return
                if parsed.path == "/accept-stage12":
                    self._write_json(
                        HTTPStatus.OK,
                        self.server.reply_service.accept_stage12(
                            thread_key=str(payload.get("thread_key", "")).strip() or None,
                            chat_name=str(payload.get("chat_name", "")).strip() or None,
                            channel=str(payload.get("channel", "wechat")).strip() or "wechat",
                            sender=str(payload.get("sender", "")).strip() or None,
                            iterations=int(payload.get("iterations", 1) or 1),
                            warmup=int(payload.get("warmup", 1) or 1),
                        ),
                    )
                    return
                if parsed.path == "/accept-stage13":
                    self._write_json(
                        HTTPStatus.OK,
                        self.server.reply_service.accept_stage13(
                            thread_key=str(payload.get("thread_key", "")).strip() or None,
                            chat_name=str(payload.get("chat_name", "")).strip() or None,
                            channel=str(payload.get("channel", "wechat")).strip() or "wechat",
                            sender=str(payload.get("sender", "")).strip() or None,
                            iterations=int(payload.get("iterations", 1) or 1),
                            warmup=int(payload.get("warmup", 1) or 1),
                        ),
                    )
                    return
                if parsed.path == "/replay-calibration-fixture":
                    self._write_json(
                        HTTPStatus.OK,
                        self.server.reply_service.replay_calibration_fixture(
                            source_type=str(payload.get("source_type", "synthetic_fixture")).strip() or "synthetic_fixture",
                            fixture_path=str(payload.get("fixture_path", "")).strip() or None,
                            thread_key=str(payload.get("thread_key", "")).strip() or None,
                            chat_name=str(payload.get("chat_name", "")).strip() or None,
                            channel=str(payload.get("channel", "wechat")).strip() or "wechat",
                            limit=int(payload.get("limit", 8) or 8),
                            artifact_dir=str(payload.get("artifact_dir", "")).strip() or None,
                        ),
                    )
                    return
                if parsed.path == "/replay-policy-regret":
                    self._write_json(
                        HTTPStatus.OK,
                        self.server.reply_service.replay_policy_regret(
                            source_type=str(payload.get("source_type", "synthetic_fixture")).strip() or "synthetic_fixture",
                            fixture_path=str(payload.get("fixture_path", "")).strip() or None,
                            thread_key=str(payload.get("thread_key", "")).strip() or None,
                            chat_name=str(payload.get("chat_name", "")).strip() or None,
                            channel=str(payload.get("channel", "wechat")).strip() or "wechat",
                            limit=int(payload.get("limit", 8) or 8),
                            artifact_dir=str(payload.get("artifact_dir", "")).strip() or None,
                        ),
                    )
                    return
                if parsed.path == "/accept-stage14":
                    self._write_json(
                        HTTPStatus.OK,
                        self.server.reply_service.accept_stage14(
                            source_type=str(payload.get("source_type", "synthetic_fixture")).strip() or "synthetic_fixture",
                            fixture_path=str(payload.get("fixture_path", "")).strip() or None,
                            thread_key=str(payload.get("thread_key", "")).strip() or None,
                            chat_name=str(payload.get("chat_name", "")).strip() or None,
                            channel=str(payload.get("channel", "wechat")).strip() or "wechat",
                            limit=int(payload.get("limit", 8) or 8),
                            artifact_dir=str(payload.get("artifact_dir", "")).strip() or None,
                        ),
                    )
                    return
                if parsed.path == "/accept-stage16":
                    self._write_json(
                        HTTPStatus.OK,
                        self.server.reply_service.accept_stage16(
                            run_pytest=bool(payload.get("run_pytest", False)),
                            artifact_dir=str(payload.get("artifact_dir", "")).strip() or None,
                        ),
                    )
                    return
                if parsed.path == "/accept-stage17":
                    self._write_json(
                        HTTPStatus.OK,
                        self.server.reply_service.accept_stage17(
                            thread_key=str(payload.get("thread_key", "")).strip() or None,
                            chat_name=str(payload.get("chat_name", "")).strip() or None,
                            channel=str(payload.get("channel", "wechat")).strip() or "wechat",
                            sender=str(payload.get("sender", "")).strip() or None,
                            artifact_dir=str(payload.get("artifact_dir", "")).strip() or None,
                        ),
                    )
                    return
                if parsed.path == "/accept-processor-fabric":
                    self._write_json(HTTPStatus.OK, self.server.reply_service.accept_processor_fabric())
                    return
                if parsed.path == "/accept-stage33":
                    self._write_json(HTTPStatus.OK, self.server.reply_service.accept_stage33())
                    return
                if parsed.path == "/accept-stage34":
                    self._write_json(HTTPStatus.OK, self.server.reply_service.accept_stage34())
                    return
                if parsed.path == "/accept-stage35":
                    self._write_json(HTTPStatus.OK, self.server.reply_service.accept_stage35())
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
