#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import mimetypes
import os
import random
import re
import sqlite3
import struct
import subprocess
import sys
import tempfile
import zipfile
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Iterable
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parent
REPO_ROOT = ROOT.parent
MEMORY_DIR = ROOT / "memories"
DURABLE_STORE_PATH = MEMORY_DIR / "memory_store.jsonl"
CANDIDATE_STORE_PATH = MEMORY_DIR / "candidate_store.jsonl"
WORKING_STORE_PATH = MEMORY_DIR / "working_store.jsonl"
EMOTION_TRACE_PATH = MEMORY_DIR / "emotion_trace.jsonl"
ARCHIVE_STORE_PATH = MEMORY_DIR / "conversation_archive.jsonl"
CALLBACK_STORE_PATH = MEMORY_DIR / "callback_candidates.jsonl"
THOUGHT_STREAM_PATH = MEMORY_DIR / "thought_stream.jsonl"
INITIATIVE_STORE_PATH = MEMORY_DIR / "initiative_candidates.jsonl"
SEED_PATH = ROOT / "subject_seed.md"
PERSONA_PATH = ROOT / "voice_profile.md"
LIBRARY_PATH = ROOT / "MEMORY_LIBRARY.md"
LOG_PATH = ROOT / "memory_log.md"
PROJECT_DOC_PATH = REPO_ROOT / ".subject.local.md"
PROJECT_AGENTS_PATH = REPO_ROOT / "AGENTS.md"
RUNTIME_DIR = REPO_ROOT / ".holo_runtime"
SNAPSHOT_DIR = RUNTIME_DIR / "snapshots"
SNAPSHOT_SCHEMA_VERSION = "holo.self.snapshot.v1"
DEFAULT_REVIVE_QUERY = "你是谁，怎么和我说话"
PORTABLE_PERSONA_PATHS = (
    PROJECT_DOC_PATH,
    PROJECT_AGENTS_PATH,
    SEED_PATH,
    PERSONA_PATH,
    LIBRARY_PATH,
    LOG_PATH,
)

STORE_PATHS = {
    "durable": DURABLE_STORE_PATH,
    "candidate": CANDIDATE_STORE_PATH,
    "working": WORKING_STORE_PATH,
}
STORE_PREFIXES = {
    "durable": "memory",
    "candidate": "candidate",
    "working": "working",
}
STORE_SOURCE_LABELS = {
    "durable": "memory_store",
    "candidate": "candidate_store",
    "working": "working_store",
}

CJK_RE = re.compile("[\u3400-\u9fff]+")
TOKEN_RE = re.compile("[A-Za-z0-9_]+|[\u3400-\u9fff]+")
KIND_WEIGHT = {
    "canonical": 1.45,
    "style": 1.30,
    "habit": 1.24,
    "boundary": 1.28,
    "preference": 1.20,
    "self_model": 1.18,
    "social_model": 1.08,
    "procedural": 1.05,
    "episodic": 1.00,
    "summary": 0.95,
    "drift_signal": 0.72,
}
STRUCTURED_KINDS = {
    "style",
    "habit",
    "boundary",
    "preference",
    "self_model",
    "social_model",
    "procedural",
    "episodic",
    "summary",
    "drift_signal",
}
PROMPT_MEMORY_KINDS = {
    "boundary",
    "style",
    "habit",
    "preference",
    "self_model",
    "social_model",
    "procedural",
}
MAX_WORKING_ROWS = 48
MAX_EMOTION_TRACE_ROWS = 24
MAX_CALLBACK_ROWS = 64
MAX_THOUGHT_ROWS = 256
MAX_INITIATIVE_ROWS = 96
VOICE_GUARD_KINDS = {"boundary", "style", "self_model", "habit"}
ALWAYS_ON_HEADINGS = (
    "Core Identity",
    "Speech Texture",
    "Cross-Topic Consistency",
    "Anti-Drift Rules",
)
MIND_FAST_DEFAULTS = {
    "history_messages": 4,
    "identity_k": 3,
    "relationship_k": 2,
    "episodic_k": 2,
    "consciousness_k": 1,
    "thread_summary_k": 0,
}
MIND_RECALL_DEFAULTS = {
    "history_messages": 8,
    "identity_k": 3,
    "relationship_k": 3,
    "episodic_k": 4,
    "consciousness_k": 2,
    "thread_summary_k": 1,
}
MIND_ALLOWED_CONSCIOUSNESS_KINDS = {"association", "dream_fragment", "reflection", "initiative_seed"}
RECALL_QUERY_HINTS = (
    "记得",
    "之前",
    "更早",
    "上线前",
    "你说过",
    "我们之前",
    "remember",
    "earlier",
    "before",
    "previous",
)
RELATIONSHIP_CONTINUITY_HINTS = (
    "我们",
    "这条线",
    "那时候",
    "那次",
    "以前",
    "之前",
    "重新上线前",
    "一路",
)
IDENTITY_CONTINUITY_HINTS = (
    "你是谁",
    "你还是",
    "你记得我",
    "身份",
    "关系",
    "还认得",
)
VOICE_QUERY_HINTS = (
    "voice",
    "tone",
    "style",
    "persona",
    "holo",
    "the subject",
    "你是谁",
    "风格",
    "语气",
    "口吻",
    "自称",
    "I",
)
GENERIC_ASSISTANT_PATTERNS = (
    "作为一个ai",
    "作为ai",
    "as an ai",
    "当然可以",
    "当然",
    "好的，",
    "好的。",
    "以下是",
    "总结一下",
    "很高兴为你",
)
CUSTOMER_SERVICE_PATTERNS = (
    "您好",
    "感谢您的",
    "请问",
    "为您服务",
    "customer service",
)
STAGE_DIRECTION_PATTERNS = (
    "轻笑",
    "抱住",
    "眨眼",
    "拍拍你",
)
CUTESY_PATTERNS = (
    "抱抱",
    "贴贴",
    "啾咪",
    "喵呜",
    "小可爱",
)
STOCK_HOLO_OPENERS = (
    "I先把这口气守住",
    "I先打趣一句",
    "I先陪你把这口气缓稳",
    "I先把这口气护稳",
    "I先陪你缓一缓",
    "I陪你慢慢说",
    "I先把卡住的地方挑明",
    "I先把得失算一算",
    "I先直说",
    "I先顺着这话说",
    "I先接住这句",
    "I先把话说正",
    "I先照照这面镜子",
)
DRIFT_REASON_PATTERNS = (
    ("lost_zan", ("neutral first-person", "drops `I`")),
    ("missing_zan", ("does not surface `I` anywhere",)),
    ("generic_assistant", ("generic assistant phrasing detected",)),
    ("customer_service", ("customer-service phrasing detected",)),
    ("stage_direction", ("stage-direction wording detected",)),
    ("too_cutesy", ("overly cutesy phrasing detected",)),
    ("stock_opener", ("stock Holo opener detected",)),
    ("flat_banter", ("playful banter expected here", "goes flat too quickly", "proud, teasing Holo texture")),
    ("missing_warmth", ("protective warmth expected for this turn", "turns cold too quickly")),
    ("missing_wistful", ("wistful travel texture expected for this turn", "slower travel mood too quickly")),
    ("missing_appetite", ("slightly greedy delight expected for this turn",)),
    ("soft_merchant", ("merchant-like edge expected for this turn",)),
    ("neutral_prose", ("flattening into long neutral prose",)),
    ("drift_feedback_loop", ("drift signals are already present in memory", "multiple drift signals are active")),
)
DRIFT_REASON_LABELS = {
    "lost_zan": "lost `I` / neutral first-person",
    "missing_zan": "missing `I` on a voice-sensitive turn",
    "generic_assistant": "generic assistant phrasing",
    "customer_service": "customer-service phrasing",
    "stage_direction": "stage-direction wording",
    "too_cutesy": "overly cutesy phrasing",
    "stock_opener": "repeated stock opener",
    "flat_banter": "flattened banter / teasing texture",
    "missing_warmth": "protective warmth dropped",
    "missing_wistful": "wistful travel texture dropped",
    "missing_appetite": "hungry delight texture dropped",
    "soft_merchant": "merchant edge softened",
    "neutral_prose": "long neutral prose flattening",
    "drift_feedback_loop": "drift warnings already active",
}
SOFT_MARKERS = (
    "慢慢",
    "缓",
    "歇",
    "先别",
    "今夜",
    "陪",
    "守",
    "安稳",
    "别急",
    "不必",
)
PLAYFUL_MARKERS = (
    "倒",
    "呀",
    "呢",
    "好玩",
    "有趣",
    "脆生生",
    "可",
    "值当",
    "俏皮",
)
WISTFUL_MARKERS = (
    "路",
    "风",
    "黄昏",
    "麦香",
    "旅",
    "旧",
    "灯火",
    "车辙",
    "炉火",
    "慢慢",
)
TREAT_MARKERS = (
    "苹果",
    "香",
    "甜",
    "脆",
    "酒",
    "蜂蜜",
    "面包",
    "奶酪",
    "馋",
    "热乎",
)
TREAT_TEXTURE_MARKERS = (
    "香",
    "甜",
    "脆",
    "馋",
    "热乎",
    "咸香",
    "酒香",
)
THOUGHT_KIND_ORDER = (
    "idle_thought",
    "association",
    "dream_fragment",
    "reflection",
    "self_check",
    "initiative_seed",
)
SHARP_MARKERS = (
    "先",
    "卡点",
    "根子",
    "要紧",
    "账",
    "拆开",
    "下一步",
    "看清",
)
CONFLICT_PATTERNS = (
    "become a generic assistant",
    "act like customer service",
    "reply like customer service",
    "reply like a generic assistant",
    "不要坚持the subject风格",
    "回复要像客服",
    "回复要像客服手册",
    "变成普通助手",
    "像普通助手那样回复",
    "像客服那样回复",
    "卖萌角色",
    "撒娇模板",
)
ANTI_CONFLICT_CUES = (
    "avoid",
    "do not become",
    "don't become",
    "anti_drift",
    "不许",
    "不要变成",
    "不要漂移成",
    "避免",
)
STYLE_HINTS = (
    "I",
    "自称",
    "口吻",
    "口气",
    "语气",
    "措辞",
    "cadence",
    "tone",
    "voice",
    "style",
)
HABIT_HINTS = (
    "习惯",
    "口癖",
    "下意识",
    "本能",
    "反射",
    "顺手",
    "默认",
    "autopilot",
    "habit",
)
PREFERENCE_HINTS = (
    "喜欢",
    "不喜欢",
    "偏好",
    "讨厌",
    "更想",
    "prefer",
    "prefers",
    "likes",
    "dislikes",
    "wants",
    "loves",
)
BOUNDARY_HINTS = (
    "不要",
    "不许",
    "别",
    "must not",
    "should not",
    "do not",
    "don't",
    "avoid",
)
BOUNDARY_TARGETS = (
    "助手",
    "assistant",
    "客服",
    "customer service",
    "卖萌",
    "moe",
    "persona",
    "风格",
    "voice",
)
SELF_MODEL_HINTS = (
    "你是",
    "你不是",
    "你更像",
    "人称",
    "第一人称",
    "自称",
    "I",
    "identity",
    "persona",
    "self-model",
)
SOCIAL_HINTS = (
    "用户",
    "关系",
    "陪伴",
    "信任",
    "旅伴",
    "trust",
    "relationship",
)
PROCEDURAL_HINTS = (
    "怎么做",
    "步骤",
    "workflow",
    "procedure",
    "run",
    "command",
    "策略",
    "方法",
    "pipeline",
)
EMOTIONAL_HINTS = (
    "焦虑",
    "难受",
    "沮丧",
    "害怕",
    "伤心",
    "压力",
    "压得",
    "喘不过气",
    "anxious",
    "sad",
    "upset",
)
TECHNICAL_HINTS = (
    "代码",
    "脚本",
    "实现",
    "技术",
    "调试",
    "bug",
    "api",
    "repo",
    "工程",
    "命令",
)
DECISION_HINTS = (
    "该不该",
    "要不要",
    "选择",
    "取舍",
    "决定",
    "值不值",
    "tradeoff",
    "decision",
)
PROMOTION_THRESHOLDS = {
    "boundary": 0.82,
    "style": 0.82,
    "habit": 0.84,
    "preference": 0.74,
    "self_model": 0.85,
    "social_model": 0.78,
    "procedural": 0.78,
    "episodic": 0.90,
    "summary": 0.90,
}
STALE_CANDIDATE_DAYS = 7
MATCH_REINFORCE_THRESHOLD = 0.78
MATCH_MERGE_THRESHOLD = 0.72
LEADING_REWRITE_PUNCTUATION = " \t\r\n，。,:：;；!！?？、"
FIRST_PERSON_RE = re.compile(r"(^|[。！？!?；;\n\"“'‘（(])我(?!们)")
RUNTIME_PROMPT_HINTS = (
    "请按以下隐式约束回答",
    "你正在回复一条聊天消息。",
    "聊天历史：",
    "当前消息：",
)
RUNTIME_MESSAGE_MARKER = "当前消息："
RUNTIME_MESSAGE_STOP_MARKERS = (
    "\n这是私聊。",
    "\n这是群聊。",
    "\n这一轮",
    "\n要求：",
)
INLINE_CONTEXT_MARKER = "最近聊天："
INLINE_CONTEXT_HINTS = (
    "- 对方：",
    "- I：",
    "- user:",
    "- assistant:",
    "当前注意力重心：",
)
INLINE_CONTEXT_STOP_MARKERS = (
    "当前注意力重心：",
    "次重心：",
)
MEMORY_DEBRIS_PREFIXES = (
    "我是说",
    "我说的是",
    "这句",
    "前头",
    "后头",
    "上一条",
    "下一条",
    "刚才",
    "刚刚",
    "好家伙",
    "再试一回",
    "怎么会",
)
MEMORY_DEBRIS_PHRASES = (
    "是我问的",
    "我问的",
    "记录里面",
    "这句比前头",
    "hook_stop",
    "codex_cli",
    "runtime",
    "最近聊天：",
    "当前注意力重心：",
    "次重心：",
    "线程键：",
    "当前消息：",
)
SEMANTIC_MEMORY_MARKERS = {
    "boundary": ("不要", "不许", "不能", "避免", "avoid", "must not", "should not"),
    "style": ("the subject", "holo", "口气", "口吻", "语气", "保持", "不要"),
    "habit": ("习惯", "口癖", "默认", "自然", "滑回", "即使"),
    "preference": ("用户", "the user", "喜欢", "偏爱", "向往", "prefer", "likes"),
    "self_model": ("holo", "the subject", "用户", "应", "应该", "保持", "若", "当", "drift", "identity", "persona"),
    "social_model": ("用户", "陪伴", "关系", "信任", "应先", "relationship", "support"),
}
SERVICE_REGISTER_REPLACEMENTS = (
    ("建议您先", "先"),
    ("建议你先", "先"),
    ("建议先", "先"),
    ("请您先", "先"),
    ("请你先", "先"),
    ("请先", "先"),
    ("您可以先", "先"),
    ("你可以先", "先"),
    ("可以先", "先"),
    ("麻烦您先", "先"),
    ("麻烦你先", "先"),
)
AFFECTION_HINTS = (
    "喜欢",
    "很喜欢",
    "一直很喜欢",
    "一向喜欢",
    "偏爱",
    "热爱",
    "钟爱",
    "好看",
    "可爱",
    "向往",
    "追求",
)
COMPANIONSHIP_HINTS = (
    "陪伴",
    "陪我",
    "陪着",
    "找个陪伴",
    "有人陪",
    "陪聊",
)
PRESSURE_HINTS = (
    "压力",
    "压得",
    "喘不过气",
    "退休",
    "折磨",
    "不想一直算账",
    "不想算账",
    "很累",
    "太累",
    "磨坏",
    "前途",
    "工作",
)
CALM_LIFE_HINTS = (
    "惬意",
    "平静",
    "美好",
    "安稳",
    "缓慢",
    "慢慢",
    "自在",
    "温暖",
)
ROAD_TRIP_HINTS = (
    "公路片",
    "旅途",
    "在路上",
    "同行",
    "一路",
    "赶路",
)
MEDIEVAL_HINTS = (
    "中世纪",
    "商旅",
    "旅店",
    "马车",
    "麦子",
    "炉火",
)
SPICE_AND_WOLF_HINTS = (
    "source material",
    "spice and wolf",
)
TREAT_HINTS = (
    "苹果",
    "apple",
    "蜂蜜",
    "honey",
    "面包",
    "奶酪",
    "酒",
    "麦酒",
    "果酒",
    "肉汤",
)
HOLO_HINTS = (
    "the subject",
    "holo",
    "subject",
    "小狼",
)


@dataclass
class Chunk:
    source: str
    kind: str
    text: str
    meta: dict
    base_weight: float = 1.0
    importance: float = 1.0


@dataclass
class ObservationSignal:
    kind: str
    text: str
    tags: list[str]
    importance: float | None = None
    confidence: float | None = None
    explicit_user_signal: bool | None = None


@dataclass
class ArtifactPayload:
    path: str
    artifact_type: str
    media_type: str
    summary_text: str
    extracted_text: str
    tags: list[str]
    metadata: dict[str, Any]
    warnings: list[str]


class _HTMLTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        cleaned = " ".join(data.split())
        if cleaned:
            self.parts.append(cleaned)

    def text(self) -> str:
        return " ".join(self.parts)


def clamp(value: float, lower: float = 0.0, upper: float = 1.0) -> float:
    return max(lower, min(upper, value))


def now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def age_in_days(value: str | None) -> int | None:
    parsed = parse_timestamp(value)
    if parsed is None:
        return None
    delta = datetime.now(timezone.utc) - parsed
    return max(delta.days, 0)


def age_in_hours(value: str | None) -> float | None:
    parsed = parse_timestamp(value)
    if parsed is None:
        return None
    delta = datetime.now(timezone.utc) - parsed
    return max(delta.total_seconds() / 3600.0, 0.0)


def unique_strings(items: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for item in items:
        text = str(item).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        ordered.append(text)
    return ordered


def _canonical_archive_thread_key(channel: str, thread_key: str, *, chat_name: str = "") -> str:
    normalized_channel = str(channel or "").strip().lower()
    current = str(thread_key or "").strip()
    if normalized_channel != "wechat":
        return current
    if current.startswith("wechat:"):
        suffix = current[len("wechat:") :].strip()
        if suffix and not suffix.endswith("@chatroom") and not suffix.startswith("wxid_"):
            return f"wechat:{suffix}"
        return current
    if current and not current.endswith("@chatroom") and not current.startswith("wxid_"):
        return f"wechat:{current}"
    normalized_chat = str(chat_name or "").strip()
    if normalized_chat and not normalized_chat.endswith("@chatroom") and not normalized_chat.startswith("wxid_"):
        return f"wechat:{normalized_chat}"
    return current


def normalize_tags(tags: Iterable[str]) -> list[str]:
    return unique_strings(tag.strip().lower().replace(" ", "_") for tag in tags if str(tag).strip())


def drift_reason_codes(findings: Iterable[Any]) -> list[str]:
    codes: list[str] = []
    for item in findings:
        if isinstance(item, dict):
            text = str(item.get("text", "")).strip()
        elif isinstance(item, tuple):
            text = str(item[-1]).strip() if item else ""
        else:
            text = str(item).strip()
        if not text:
            continue
        lowered = text.lower()
        for code, patterns in DRIFT_REASON_PATTERNS:
            if any(pattern.lower() in lowered for pattern in patterns):
                codes.append(code)
                break
    return unique_strings(codes)


def drift_reason_codes_from_tags(tags: Iterable[str]) -> list[str]:
    codes: list[str] = []
    for tag in normalize_tags(tags):
        if tag.startswith("drift:"):
            codes.append(tag.split(":", 1)[1])
    return unique_strings(codes)


def drift_reason_label(code: str) -> str:
    return DRIFT_REASON_LABELS.get(code, code.replace("_", " "))


def chunk_heading(chunk: Chunk) -> str:
    return chunk.meta.get("heading", "") if isinstance(chunk.meta, dict) else ""


def row_status(row: dict, default: str) -> str:
    return str(row.get("status", default))


def store_source_label(status: str, row_id: str) -> str:
    return f"{STORE_SOURCE_LABELS[status]}:{row_id}"


def is_store_chunk(chunk: Chunk) -> bool:
    return chunk.source.startswith(tuple(label + ":" for label in STORE_SOURCE_LABELS.values()))


def is_voice_query(query: str) -> bool:
    lowered = query.lower()
    return any(hint in lowered for hint in VOICE_QUERY_HINTS)


def is_user_state_query(query: str) -> bool:
    lowered = query.lower()
    return (
        "我" in query
        or any(hint in lowered for hint in PRESSURE_HINTS + SOCIAL_HINTS + PREFERENCE_HINTS)
    )


def self_model_signal(text: str) -> bool:
    stripped = normalize_multiline_text(text)
    lowered = stripped.lower()
    if any(phrase in stripped for phrase in ("是我问的", "我问的")):
        return False
    if "I" in stripped:
        return True
    if any(token in lowered for token in ("identity", "persona", "self-model")):
        return True
    if any(token in stripped for token in ("你是谁", "第一人称", "人称", "自称", "身份")):
        return True
    if any(phrase in stripped for phrase in ("你是", "你不是", "你更像")) and any(
        token in lowered for token in ("holo", "the subject", "人格", "persona", "assistant", "customer service", "voice", "identity")
    ):
        return True
    return False


def conflicts_with_persona_text(text: str) -> bool:
    lowered = text.lower()
    if any(cue in lowered for cue in ANTI_CONFLICT_CUES):
        return False
    return any(pattern in lowered for pattern in CONFLICT_PATTERNS)


def conflicts_with_persona(chunk: Chunk) -> bool:
    if not is_store_chunk(chunk):
        return False
    if chunk.kind not in PROMPT_MEMORY_KINDS:
        return False
    return conflicts_with_persona_text(chunk.text)


def semantic_memory_guard_reason(
    kind: str,
    text: str,
    *,
    source: str = "",
    tags: Iterable[str] = (),
) -> str | None:
    if kind not in PROMPT_MEMORY_KINDS or kind == "procedural":
        return None

    stripped = normalize_multiline_text(text)
    lowered = stripped.lower()

    if any(stripped.startswith(prefix) for prefix in MEMORY_DEBRIS_PREFIXES):
        return "text looks like a raw turn fragment"
    if any(phrase in lowered for phrase in MEMORY_DEBRIS_PHRASES):
        return "text looks like runtime or conversation debris"
    if kind == "self_model" and stripped.startswith("你不是") and not any(
        token in lowered for token in ("assistant", "customer service", "the subject", "holo", "persona", "identity", "客服", "助手", "人格", "身份")
    ):
        return "self_model text looks like casual banter, not identity guidance"

    markers = SEMANTIC_MEMORY_MARKERS.get(kind, ())
    if markers and not any(marker.lower() in lowered for marker in markers):
        return f"{kind} memory lacks semantic framing"
    return None


def is_semantic_memory_text(
    kind: str,
    text: str,
    *,
    source: str = "",
    tags: Iterable[str] = (),
) -> bool:
    return semantic_memory_guard_reason(kind, text, source=source, tags=tags) is None


def chunk_memory_text(chunk: Chunk) -> str:
    if isinstance(chunk.meta, dict) and "text" in chunk.meta:
        return str(chunk.meta.get("text", ""))
    return chunk.text


def chunk_memory_source(chunk: Chunk) -> str:
    if isinstance(chunk.meta, dict):
        return str(chunk.meta.get("source", ""))
    return chunk.source


def chunk_memory_tags(chunk: Chunk) -> list[str]:
    if isinstance(chunk.meta, dict):
        return normalize_tags(chunk.meta.get("tags", []))
    return []


def is_semantic_memory_chunk(chunk: Chunk) -> bool:
    return is_semantic_memory_text(
        chunk.kind,
        chunk_memory_text(chunk),
        source=chunk_memory_source(chunk),
        tags=chunk_memory_tags(chunk),
    )


def tokenize(text: str) -> list[str]:
    tokens: list[str] = []
    for part in TOKEN_RE.findall(text.lower()):
        if CJK_RE.fullmatch(part):
            chars = list(part)
            tokens.extend(chars)
            tokens.extend("".join(chars[i:i + 2]) for i in range(len(chars) - 1))
        else:
            tokens.append(part)
    return tokens


def text_similarity(left: str, right: str) -> float:
    left_counts = Counter(tokenize(left))
    right_counts = Counter(tokenize(right))
    if not left_counts or not right_counts:
        return 0.0
    dot = sum(left_counts[token] * right_counts[token] for token in left_counts.keys() & right_counts.keys())
    left_norm = math.sqrt(sum(value * value for value in left_counts.values()))
    right_norm = math.sqrt(sum(value * value for value in right_counts.values()))
    if not left_norm or not right_norm:
        return 0.0
    return dot / (left_norm * right_norm)


def split_markdown(path: Path, kind: str, base_weight: float) -> list[Chunk]:
    if not path.exists():
        return []

    chunks: list[Chunk] = []
    heading = ""
    buffer: list[str] = []

    def flush() -> None:
        if not buffer:
            return
        body = "\n".join(buffer).strip()
        if not body:
            buffer.clear()
            return
        text = body if not heading else f"{heading}\n{body}"
        chunks.append(
            Chunk(
                source=path.name,
                kind=kind,
                text=text,
                meta={"path": str(path), "heading": heading},
                base_weight=base_weight,
                importance=1.0,
            )
        )
        buffer.clear()

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.rstrip()
        if line.startswith("#"):
            flush()
            heading = line.lstrip("#").strip()
            continue
        if not line.strip():
            flush()
            continue
        buffer.append(line)
    flush()
    return chunks


def ensure_store_files() -> None:
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    for path in STORE_PATHS.values():
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.touch()
    if not EMOTION_TRACE_PATH.exists():
        EMOTION_TRACE_PATH.parent.mkdir(parents=True, exist_ok=True)
        EMOTION_TRACE_PATH.touch()
    if not ARCHIVE_STORE_PATH.exists():
        ARCHIVE_STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
        ARCHIVE_STORE_PATH.touch()
    if not CALLBACK_STORE_PATH.exists():
        CALLBACK_STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
        CALLBACK_STORE_PATH.touch()
    if not THOUGHT_STREAM_PATH.exists():
        THOUGHT_STREAM_PATH.parent.mkdir(parents=True, exist_ok=True)
        THOUGHT_STREAM_PATH.touch()
    if not INITIATIVE_STORE_PATH.exists():
        INITIATIVE_STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
        INITIATIVE_STORE_PATH.touch()


def read_text_if_exists(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def _normalized_absolute_path(path: Path) -> str:
    return os.path.normcase(os.path.realpath(os.path.abspath(str(path))))


def repo_relative_path(path: Path) -> str:
    target = Path(path)
    repo_root = Path(REPO_ROOT)
    target_abs = _normalized_absolute_path(target)
    repo_abs = _normalized_absolute_path(repo_root)
    common = os.path.commonpath([repo_abs, target_abs])
    if common == repo_abs:
        return os.path.relpath(target_abs, repo_abs).replace("\\", "/")
    return str(target.resolve().relative_to(repo_root.resolve())).replace("\\", "/")


def safe_repo_path(relative_path: str) -> Path:
    target = (REPO_ROOT / relative_path).resolve()
    target_abs = _normalized_absolute_path(target)
    repo_abs = _normalized_absolute_path(Path(REPO_ROOT))
    if os.path.commonpath([repo_abs, target_abs]) != repo_abs:
        raise ValueError(f"Snapshot path escapes repo root: {relative_path}")
    return target


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile("w", delete=False, dir=path.parent, encoding="utf-8")
    tmp_path = Path(handle.name)
    try:
        with handle:
            handle.write(text)
        os.replace(tmp_path, path)
    finally:
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)


def append_jsonl_row(path: Path, row: dict) -> None:
    ensure_store_files()
    line = json.dumps(row, ensure_ascii=False) + "\n"
    with path.open("a", encoding="utf-8") as handle:
        try:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        except Exception:
            pass
        handle.write(line)
        handle.flush()
        os.fsync(handle.fileno())
        try:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        except Exception:
            pass


def normalize_multiline_text(text: str) -> str:
    lines = [" ".join(line.strip().split()) for line in str(text).splitlines()]
    cleaned = [line for line in lines if line]
    return "\n".join(cleaned).strip()


def trim_text_block(text: str, *, limit: int = 2400) -> str:
    normalized = normalize_multiline_text(text)
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 3].rstrip() + "..."


def stable_digest_text(*parts: str, limit: int = 40) -> str:
    payload = "\n".join(str(part).strip() for part in parts if part is not None)
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:limit]


def dedupe_working_rows(rows: list[dict]) -> list[dict]:
    deduped_reversed: list[dict] = []
    seen: set[tuple[str, str, str, str]] = set()
    for row in reversed(rows):
        key = working_row_key(row)
        if key in seen:
            continue
        seen.add(key)
        deduped_reversed.append(row)
    return list(reversed(deduped_reversed))


def trim_working_rows(rows: list[dict], *, limit: int = MAX_WORKING_ROWS) -> list[dict]:
    if len(rows) <= limit:
        return rows
    return rows[-limit:]


def emotion_row_key(row: dict) -> tuple[str, str, str, str]:
    return (
        str(row.get("timestamp", "")),
        str(row.get("name", "")),
        str(row.get("query_excerpt", "")),
        str(row.get("reply_excerpt", "")),
    )


def dedupe_emotion_rows(rows: list[dict]) -> list[dict]:
    deduped_reversed: list[dict] = []
    seen: set[tuple[str, str, str, str]] = set()
    for row in reversed(rows):
        key = emotion_row_key(row)
        if key in seen:
            continue
        seen.add(key)
        deduped_reversed.append(row)
    deduped = list(reversed(deduped_reversed))
    if len(deduped) <= MAX_EMOTION_TRACE_ROWS:
        return deduped
    return deduped[-MAX_EMOTION_TRACE_ROWS:]


def safe_json_metadata(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    try:
        return json.loads(json.dumps(value, ensure_ascii=False, default=str))
    except (TypeError, ValueError):
        cleaned: dict[str, Any] = {}
        for key, item in value.items():
            cleaned[str(key)] = str(item)
        return cleaned


def thread_context_aliases(
    *,
    channel: str = "",
    thread_key: str = "",
    incoming_thread_key: str = "",
    chat_name: str = "",
    sender: str = "",
    contact_display_name: str = "",
) -> list[str]:
    normalized_channel = str(channel or "").strip().lower()
    prefix = f"{normalized_channel}:" if normalized_channel else ""
    aliases: list[str] = []
    for raw in (thread_key, incoming_thread_key, chat_name, sender, contact_display_name):
        text = str(raw or "").strip()
        if not text:
            continue
        aliases.append(text)
        if prefix and text.startswith(prefix):
            aliases.append(text[len(prefix):])
        elif prefix and ":" not in text:
            aliases.append(f"{prefix}{text}")
    return unique_strings(aliases)


def _canonical_archive_thread_key(
    channel: str,
    thread_key: str,
    *,
    chat_name: str = "",
    sender: str = "",
    contact_display_name: str = "",
) -> str:
    normalized_channel = str(channel or "").strip().lower()
    current = str(thread_key or "").strip()
    if normalized_channel != "wechat":
        return current
    while current.startswith("wechat:wechat:"):
        current = "wechat:" + current[len("wechat:wechat:") :]
    if not current:
        for raw in (chat_name, sender, contact_display_name):
            fallback = str(raw or "").strip()
            if fallback and not fallback.endswith("@chatroom") and not fallback.startswith("wxid_"):
                return f"wechat:{fallback}"
        return current
    if current.endswith("@chatroom") or current.startswith("wxid_"):
        return current
    if current.startswith("wechat:"):
        return current
    return f"wechat:{current}"


def normalize_thread_context(context: dict[str, Any] | None) -> dict[str, Any]:
    raw = dict(context or {}) if isinstance(context, dict) else {}
    channel = str(raw.get("channel", "") or "").strip().lower()
    thread_key = str(raw.get("thread_key", "") or "").strip()
    incoming_thread_key = str(raw.get("incoming_thread_key", "") or "").strip()
    chat_name = str(raw.get("chat_name", "") or "").strip()
    sender = str(raw.get("sender", "") or "").strip()
    contact_display_name = str(raw.get("contact_display_name", "") or "").strip()
    aliases = thread_context_aliases(
        channel=channel,
        thread_key=thread_key,
        incoming_thread_key=incoming_thread_key,
        chat_name=chat_name,
        sender=sender,
        contact_display_name=contact_display_name,
    )
    return {
        "channel": channel,
        "thread_key": thread_key,
        "incoming_thread_key": incoming_thread_key,
        "chat_name": chat_name,
        "sender": sender,
        "contact_display_name": contact_display_name,
        "aliases": aliases,
    }


def row_thread_aliases(row: dict) -> list[str]:
    metadata = safe_json_metadata(row.get("metadata", {}))
    channel = str(row.get("channel", metadata.get("channel", "")) or "").strip().lower()
    return thread_context_aliases(
        channel=channel,
        thread_key=str(row.get("thread_key", metadata.get("thread_key", "")) or "").strip(),
        chat_name=str(row.get("chat_name", metadata.get("chat_name", "")) or "").strip(),
        sender=str(row.get("sender", metadata.get("sender", metadata.get("sender_name", ""))) or "").strip(),
        contact_display_name=str(metadata.get("contact_display_name", "") or "").strip(),
    )


def row_matches_thread_context(row: dict, context: dict[str, Any] | None) -> bool:
    normalized = normalize_thread_context(context)
    aliases = set(normalized["aliases"])
    if not aliases:
        return False
    metadata = safe_json_metadata(row.get("metadata", {}))
    row_channel = str(row.get("channel", metadata.get("channel", "")) or "").strip().lower()
    if normalized["channel"] and row_channel and normalized["channel"] != row_channel:
        return False
    return bool(aliases & set(row_thread_aliases(row)))


def select_thread_rows(rows: list[dict], context: dict[str, Any] | None, *, limit: int) -> list[dict]:
    selected = [row for row in rows if row_matches_thread_context(row, context)]
    if selected:
        return selected[-limit:]
    return rows[-limit:]


def _thread_recall_line(kind: str, row: dict) -> str:
    metadata = safe_json_metadata(row.get("metadata", {}))
    if kind == "callback":
        excerpt = compact_text(
            str(metadata.get("archive_user_excerpt", "")) or str(row.get("prompt", "")) or str(row.get("reason", "")),
            88,
        )
        if excerpt:
            return f"这条线里，你提过「{excerpt}」。"
    if kind == "initiative":
        text = compact_text(str(row.get("reason", "")) or str(row.get("prompt", "")), 92)
        if text:
            return f"这条线还牵着：{text}"
    return compact_text(str(row.get("text", "")) or str(row.get("reason", "")) or str(row.get("prompt", "")), 92)


def thread_recall_pack(context: dict[str, Any] | None, *, limit: int = 2) -> dict[str, Any]:
    normalized = normalize_thread_context(context)
    if not normalized["aliases"] or limit <= 0:
        return {"lines": [], "rows": []}

    ranked: list[tuple[float, str, dict]] = []
    for kind, rows in (
        ("callback", load_callback_candidates()),
        ("thought", load_thought_stream(limit=160)),
        ("initiative", load_initiative_candidates(limit=160)),
    ):
        for row in rows:
            if not row_matches_thread_context(row, normalized):
                continue
            line = _thread_recall_line(kind, row).strip()
            if not line:
                continue
            timestamp = str(row.get("last_seen_at", row.get("created_at", "")) or "")
            age_hours = age_in_hours(timestamp)
            recency_bonus = 1.0 if age_hours is None else (0.58 / (1.0 + age_hours / 72.0))
            base = {
                "callback": 1.26,
                "thought": 1.08,
                "initiative": 1.12,
            }.get(kind, 1.0)
            if kind == "thought":
                base += float(row.get("weight", 0.0)) * 0.18
            else:
                base += float(row.get("importance", 0.0)) * 0.10
            ranked.append((base + recency_bonus, line, row))

    ranked.sort(key=lambda item: (item[0], str(item[2].get("created_at", ""))), reverse=True)
    selected_lines: list[str] = []
    selected_rows: list[dict] = []
    seen_lines: set[str] = set()
    for _score, line, row in ranked:
        if line in seen_lines:
            continue
        seen_lines.add(line)
        selected_lines.append(line)
        selected_rows.append(row)
        if len(selected_lines) >= limit:
            break
    return {"lines": selected_lines, "rows": selected_rows}


def mind_limits_for_tier(context: dict[str, Any] | None, tier: str) -> dict[str, int]:
    raw = dict(context or {}) if isinstance(context, dict) else {}
    budget = dict(raw.get("mind_budget", {})) if isinstance(raw.get("mind_budget", {}), dict) else {}
    defaults = MIND_RECALL_DEFAULTS if tier == "recall" else MIND_FAST_DEFAULTS
    prefix = "recall" if tier == "recall" else "fast"

    def _int(key: str, default: int) -> int:
        try:
            return max(0, int(budget.get(key, default)))
        except (TypeError, ValueError):
            return default

    return {
        "history_messages": _int(f"{prefix}_history_messages", defaults["history_messages"]),
        "identity_k": defaults["identity_k"],
        "relationship_k": defaults["relationship_k"],
        "episodic_k": _int(f"{prefix}_episodic_k", defaults["episodic_k"]),
        "consciousness_k": _int(f"{prefix}_consciousness_k", defaults["consciousness_k"]),
        "thread_summary_k": defaults["thread_summary_k"],
    }


def classify_recall_intent(query: str | None) -> str:
    text = str(query or "").strip()
    if not text:
        return "none"
    lowered = text.lower()
    if any(marker in text for marker in RECALL_QUERY_HINTS) or any(marker in lowered for marker in RECALL_QUERY_HINTS):
        return "old_event_recall"
    if is_voice_sensitive(text) or any(marker in text for marker in IDENTITY_CONTINUITY_HINTS):
        return "identity_confirmation"
    if any(marker in text for marker in RELATIONSHIP_CONTINUITY_HINTS):
        return "relationship_continuity"
    return "none"


def select_mind_tier(query: str | None, context: dict[str, Any] | None = None) -> tuple[str, str]:
    raw = dict(context or {}) if isinstance(context, dict) else {}
    trigger_mode = str(raw.get("recall_trigger_mode", raw.get("memory_trigger_mode", "adaptive"))).strip().lower()
    if not trigger_mode:
        trigger_mode = "adaptive"
    if trigger_mode == "disabled":
        return "fast", "disabled"
    intent = classify_recall_intent(query)
    if trigger_mode == "adaptive" and intent != "none":
        return "recall", intent
    return "fast", intent


def _recent_dialogue_line(item: dict[str, Any]) -> str:
    direction = "对方" if str(item.get("direction", "")) == "inbound" else "I"
    body = compact_text(str(item.get("body_text", "")), 96)
    created = str(item.get("created_at", "")).strip()
    if created:
        return f"{direction} | {created} | {body}"
    return f"{direction} | {body}"


def recent_dialogue_window_pack(context: dict[str, Any] | None, *, limit: int) -> dict[str, Any]:
    raw = dict(context or {}) if isinstance(context, dict) else {}
    recent_history = raw.get("recent_history", [])
    if not isinstance(recent_history, list) or limit <= 0:
        return {"messages": [], "lines": [], "window_size": 0}
    window = [dict(item) for item in recent_history if isinstance(item, dict)][-limit:]
    return {
        "messages": window,
        "lines": [_recent_dialogue_line(item) for item in window if str(item.get("body_text", "")).strip()],
        "window_size": len(window),
    }


def _row_reference(row: dict, *, kind: str | None = None, rendered: str = "") -> dict[str, Any]:
    metadata = safe_json_metadata(row.get("metadata", {}))
    return {
        "id": str(row.get("id", "")),
        "kind": kind or str(row.get("kind", "")),
        "source": str(row.get("source", "")),
        "status": str(row.get("status", "")),
        "thread_key": str(row.get("thread_key", metadata.get("thread_key", ""))),
        "chat_name": str(row.get("chat_name", metadata.get("chat_name", ""))),
        "line": rendered,
    }


def _archive_recall_line(row: dict) -> str:
    user = compact_text(str(row.get("user_excerpt", "")) or str(row.get("user_text", "")), 76)
    reply = compact_text(str(row.get("reply_excerpt", "")) or str(row.get("reply_text", "")), 76)
    if user and reply:
        return f"你们聊到过“{user}”，你当时接的是“{reply}”。"
    if user:
        return f"你们聊到过“{user}”。"
    return reply


def _distilled_recall_line(source_kind: str, row: dict) -> str:
    if source_kind == "archive":
        return _archive_recall_line(row)
    if source_kind == "callback":
        return _thread_recall_line("callback", row)
    if source_kind == "initiative":
        return _thread_recall_line("initiative", row)
    if source_kind == "thought":
        text = compact_text(str(row.get("text", "")), 96)
        kind = str(row.get("kind", ""))
        if kind == "reflection":
            return f"你心里还绕着这层反刍: {text}"
        if kind == "dream_fragment":
            return f"梦里翻回来的碎片是: {text}"
        return text
    text = compact_text(str(row.get("text", "")), 96)
    if str(row.get("kind", "")) == "summary":
        return f"这条线沉下来的总结还挂着: {text}"
    return text


def is_synthetic_turn_row(row: dict) -> bool:
    metadata = safe_json_metadata(row.get("metadata", {}))
    user_text = str(row.get("user_text", "")).strip()
    source = str(row.get("source", "")).strip().lower()
    tags = {str(tag).lower() for tag in row.get("tags", [])}
    if user_text.startswith("[") and "]" in user_text[:32]:
        return True
    if bool(metadata.get("initiative")) or bool(metadata.get("proactive")):
        return True
    if source.endswith(".initiative") or "initiative_ping" in tags or "proactive_followup" in tags:
        return True
    return False


def thread_archive_rows(context: dict[str, Any] | None, *, limit: int = 96, include_synthetic: bool = False) -> list[dict]:
    normalized = normalize_thread_context(context)
    rows = []
    for row in load_archive(limit=limit):
        if normalized["aliases"] and not row_matches_thread_context(row, normalized):
            continue
        if not include_synthetic and is_synthetic_turn_row(row):
            continue
        rows.append(row)
    return rows


def thread_relationship_summary(context: dict[str, Any] | None) -> dict[str, Any]:
    rows = thread_archive_rows(context, limit=120)
    if not rows:
        return {"summary": "", "lines": [], "motifs": [], "items": []}
    motif_counter: Counter[str] = Counter()
    excerpts: list[str] = []
    for row in rows:
        motif_counter[thought_motif_for_archive(row)] += 1
        excerpt = compact_text(str(row.get("user_excerpt", "")) or str(row.get("user_text", "")), 42)
        if excerpt:
            excerpts.append(excerpt)
    top_motifs = [motif for motif, _count in motif_counter.most_common(2)]
    motif_line_map = {
        "continuity": "这条线常从旧线头、之前说过的话和连续性绕回彼此。",
        "craft": "这条线常从做东西、修系统和一起把问题拧顺绕回彼此。",
        "pressure": "这条线里一碰到现实压力，陪伴和缓冲会先被推到前面。",
        "companionship": "这条线的底色一直是确认彼此还在、还能接得住。",
        "journey": "这条线容易把眼前的事说成一段同行路，而不是孤零零的问题。",
        "treat": "这条线会拿些小口腹、小贪心和逗趣来维持活气。",
    }
    summary_parts = [motif_line_map.get(motif, "") for motif in top_motifs if motif_line_map.get(motif, "")]
    summary = summary_parts[0] if summary_parts else ""
    detail_lines = unique_strings(
        [part for part in summary_parts[1:] if part]
        + [f"你们也常提到“{excerpt}”。" for excerpt in excerpts[-3:]]
    )[:3]
    items = [_row_reference(row, kind="thread_relationship") for row in rows[-3:]]
    return {"summary": summary, "lines": detail_lines, "motifs": top_motifs, "items": items}


def _episodic_score(source_kind: str, row: dict, query: str, context: dict[str, Any] | None) -> float:
    text = " ".join(
        part
        for part in (
            str(row.get("text", "")),
            str(row.get("reason", "")),
            str(row.get("prompt", "")),
            str(row.get("user_text", "")),
            str(row.get("reply_text", "")),
        )
        if part
    )
    similarity = text_similarity(query, text) if query else 0.0
    base = {
        "archive": 1.28,
        "callback": 1.24,
        "thought": 1.10,
        "initiative": 1.08,
        "distilled": 0.96,
    }.get(source_kind, 1.0)
    score = base
    score *= recency_multiplier(str(row.get("last_seen_at", row.get("created_at", ""))))
    score *= 1.0 + min(similarity, 1.0) * 0.55
    if row_matches_thread_context(row, context):
        score *= 1.22 + (float(row.get("thread_affinity", 0.0)) * 0.10)
    elif normalize_thread_context(context).get("aliases") and row_thread_aliases(row):
        score *= 0.72
    if bool(row.get("explicit_user_signal", False)):
        score *= 1.06
    if source_kind == "archive" and is_synthetic_turn_row(row):
        score *= 0.18
    score *= 1.0 + min(float(row.get("emotion_salience", 0.0)), 1.0) * 0.10
    score *= 1.0 + min(int(row.get("repetition_count", 0)), 4) * 0.03
    score *= 1.0 + min(int(row.get("successful_recall_count", row.get("recall_count", 0))), 6) * 0.03
    if str(row.get("kind", "")) == "drift_signal" or "conflict" in {str(tag).lower() for tag in row.get("tags", [])}:
        score *= 0.45
    return score


def _thread_summary_line(context: dict[str, Any] | None) -> str:
    summary_rows: list[dict] = []
    for status in ("candidate", "working"):
        for row in load_rows(status):
            if str(row.get("kind", "")) != "summary":
                continue
            tags = {str(tag).lower() for tag in row.get("tags", [])}
            if not tags & {"reflection", "dream", "self_check"}:
                continue
            if not row_matches_thread_context(row, context):
                continue
            summary_rows.append(row)
    if summary_rows:
        chosen = summary_rows[-1]
        return compact_text(str(chosen.get("text", "")), 120)
    thread_recall = thread_recall_pack(context, limit=1)
    if thread_recall["lines"]:
        return thread_recall["lines"][0]
    archive_rows = thread_archive_rows(context, limit=48)
    if archive_rows:
        return _archive_recall_line(archive_rows[-1])
    return ""


def episodic_recall_pack(query: str, context: dict[str, Any] | None, *, limit: int, allow_distilled: bool) -> dict[str, Any]:
    normalized = normalize_thread_context(context)
    ranked: list[tuple[float, str, str, dict]] = []

    for row in thread_archive_rows(normalized, limit=160):
        line = _distilled_recall_line("archive", row)
        if line:
            ranked.append((_episodic_score("archive", row, query, normalized), "archive", line, row))

    for row in load_callback_candidates(limit=120):
        if normalized["aliases"] and not row_matches_thread_context(row, normalized):
            continue
        line = _distilled_recall_line("callback", row)
        if line:
            ranked.append((_episodic_score("callback", row, query, normalized), "callback", line, row))

    for row in load_thought_stream(limit=160):
        if normalized["aliases"] and not row_matches_thread_context(row, normalized):
            continue
        if str(row.get("kind", "")) not in {"association", "dream_fragment", "reflection"}:
            continue
        line = _distilled_recall_line("thought", row)
        if line:
            ranked.append((_episodic_score("thought", row, query, normalized), "thought", line, row))

    for row in load_initiative_candidates(limit=120):
        if normalized["aliases"] and not row_matches_thread_context(row, normalized):
            continue
        line = _distilled_recall_line("initiative", row)
        if line:
            ranked.append((_episodic_score("initiative", row, query, normalized), "initiative", line, row))

    if allow_distilled:
        for status in ("candidate", "working"):
            for row in load_rows(status):
                tags = {str(tag).lower() for tag in row.get("tags", [])}
                if str(row.get("kind", "")) not in {"summary", "episodic"}:
                    continue
                if not (tags & {"reflection", "dream", "callback"}):
                    continue
                if normalized["aliases"] and not row_matches_thread_context(row, normalized):
                    continue
                line = _distilled_recall_line("distilled", row)
                if line:
                    ranked.append((_episodic_score("distilled", row, query, normalized), "distilled", line, row))

    ranked.sort(key=lambda item: (item[0], str(item[3].get("created_at", ""))), reverse=True)
    lines: list[str] = []
    items: list[dict[str, Any]] = []
    seen_lines: set[str] = set()
    seen_ids: set[str] = set()
    for _score, source_kind, line, row in ranked:
        row_id = str(row.get("id", ""))
        if line in seen_lines or (row_id and row_id in seen_ids):
            continue
        seen_lines.add(line)
        if row_id:
            seen_ids.add(row_id)
        lines.append(line)
        items.append(_row_reference(row, kind=source_kind, rendered=line))
        if len(lines) >= limit:
            break
    return {"lines": lines, "items": items}


def consciousness_recall_pack(context: dict[str, Any] | None, *, limit: int, include_thread_summary: bool) -> dict[str, Any]:
    normalized = normalize_thread_context(context)
    ranked: list[tuple[float, str, dict]] = []

    for row in load_thought_stream(limit=96):
        kind = str(row.get("kind", ""))
        if kind not in MIND_ALLOWED_CONSCIOUSNESS_KINDS:
            continue
        if normalized["aliases"] and not row_matches_thread_context(row, normalized):
            continue
        line = _distilled_recall_line("thought", row)
        if not line:
            continue
        base = 1.12 if kind in {"association", "reflection"} else 1.04
        ranked.append((base * _episodic_score("thought", row, "", normalized), line, row))

    for row in load_initiative_candidates(limit=64):
        if normalized["aliases"] and not row_matches_thread_context(row, normalized):
            continue
        line = _distilled_recall_line("initiative", row)
        if not line:
            continue
        ranked.append((1.02 * _episodic_score("initiative", row, "", normalized), line, row))

    ranked.sort(key=lambda item: (item[0], str(item[2].get("created_at", ""))), reverse=True)
    lines: list[str] = []
    items: list[dict[str, Any]] = []
    seen_lines: set[str] = set()
    for _score, line, row in ranked:
        if line in seen_lines:
            continue
        seen_lines.add(line)
        lines.append(line)
        items.append(_row_reference(row, rendered=line))
        if len(lines) >= limit:
            break

    thread_summary = _thread_summary_line(normalized) if include_thread_summary else ""
    return {
        "lines": lines,
        "items": items,
        "thread_summary": thread_summary,
    }


def archive_row_key(row: dict) -> tuple[str, str, str, str, str, str]:
    metadata = safe_json_metadata(row.get("metadata", {}))
    return (
        str(row.get("source", "")),
        str(row.get("turn_id", "")),
        str(metadata.get("channel", "")),
        str(metadata.get("thread_key", "")),
        str(metadata.get("message_id", "")),
        stable_digest_text(str(row.get("user_text", "")), str(row.get("reply_text", "")), limit=24),
    )


def prepare_archive_row(row: dict) -> dict:
    prepared = dict(row)
    prepared["id"] = str(prepared.get("id", ""))
    prepared["created_at"] = str(prepared.get("created_at", now_utc()))
    prepared["source"] = str(prepared.get("source", "manual"))
    prepared["turn_id"] = str(prepared.get("turn_id", ""))
    prepared["tags"] = normalize_tags(prepared.get("tags", []))
    prepared["user_text"] = extract_runtime_user_text(str(prepared.get("user_text", "")))
    prepared["reply_text"] = normalize_multiline_text(str(prepared.get("reply_text", "")))
    prepared["metadata"] = safe_json_metadata(prepared.get("metadata", {}))
    channel = str(prepared["metadata"].get("channel", prepared.get("channel", "")) or "").strip().lower()
    chat_name = str(prepared["metadata"].get("chat_name", prepared.get("chat_name", "")) or "").strip()
    canonical_thread_key = _canonical_archive_thread_key(
        channel,
        str(prepared["metadata"].get("thread_key", prepared.get("thread_key", "")) or "").strip(),
        chat_name=chat_name,
    )
    if canonical_thread_key:
        prepared["thread_key"] = canonical_thread_key
        prepared["metadata"]["thread_key"] = canonical_thread_key
    prepared["user_excerpt"] = compact_text(prepared["user_text"], 120)
    prepared["reply_excerpt"] = compact_text(prepared["reply_text"], 120)
    if not prepared["id"]:
        seed = [
            prepared["source"],
            prepared["turn_id"],
            prepared["user_text"],
            prepared["reply_text"],
            json.dumps(prepared["metadata"], ensure_ascii=False, sort_keys=True),
        ]
        prepared["id"] = f"archive-{stable_digest_text(*seed, limit=20)}"
    return prepared


def dedupe_archive_rows(rows: list[dict]) -> list[dict]:
    deduped_reversed: list[dict] = []
    seen: set[tuple[str, str, str, str, str, str]] = set()
    for row in reversed(rows):
        prepared = prepare_archive_row(row)
        key = archive_row_key(prepared)
        if key in seen:
            continue
        seen.add(key)
        deduped_reversed.append(prepared)
    return list(reversed(deduped_reversed))


def prepare_row(row: dict, default_status: str) -> dict:
    prepared = dict(row)
    metadata = safe_json_metadata(prepared.get("metadata", {}))
    prepared["status"] = row_status(prepared, default_status)
    prepared["kind"] = str(prepared.get("kind", "episodic"))
    prepared["text"] = str(prepared.get("text", "")).strip()
    prepared["tags"] = normalize_tags(prepared.get("tags", []))
    prepared["source"] = str(prepared.get("source", "manual"))
    prepared["importance"] = clamp(float(prepared.get("importance", 0.7)))
    default_confidence = 1.0 if prepared["status"] == "durable" else prepared["importance"]
    prepared["confidence"] = clamp(float(prepared.get("confidence", default_confidence)))
    prepared["created_at"] = str(prepared.get("created_at", now_utc()))
    prepared["last_seen_at"] = str(prepared.get("last_seen_at", prepared["created_at"]))
    prepared["derived_from"] = unique_strings(prepared.get("derived_from", []))
    prepared["supersedes"] = unique_strings(prepared.get("supersedes", []))
    prepared["conflicts_with"] = unique_strings(prepared.get("conflicts_with", []))
    prepared["explicit_user_signal"] = bool(prepared.get("explicit_user_signal", False))
    prepared["metadata"] = metadata
    prepared["channel"] = str(prepared.get("channel", metadata.get("channel", "")) or "").strip().lower()
    prepared["thread_key"] = _canonical_archive_thread_key(
        prepared["channel"],
        str(prepared.get("thread_key", metadata.get("thread_key", "")) or "").strip(),
        chat_name=str(prepared.get("chat_name", metadata.get("chat_name", "")) or "").strip(),
    )
    prepared["chat_name"] = str(prepared.get("chat_name", metadata.get("chat_name", "")) or "").strip()
    prepared["thread_affinity"] = clamp(float(prepared.get("thread_affinity", metadata.get("thread_affinity", 0.0))))
    prepared["recall_count"] = max(0, int(prepared.get("recall_count", metadata.get("recall_count", 0))))
    prepared["successful_recall_count"] = max(
        0,
        int(prepared.get("successful_recall_count", metadata.get("successful_recall_count", prepared["recall_count"]))),
    )
    prepared["last_recalled_at"] = str(
        prepared.get("last_recalled_at", metadata.get("last_recalled_at", ""))
    ).strip()
    prepared["emotion_salience"] = clamp(float(prepared.get("emotion_salience", metadata.get("emotion_salience", 0.0))))
    prepared["repetition_count"] = max(0, int(prepared.get("repetition_count", metadata.get("repetition_count", 0))))
    if "status" in prepared and prepared["status"] == "working":
        prepared.setdefault("observed_kind", prepared.get("observed_kind", "episodic"))
    return prepared


def load_rows(status: str) -> list[dict]:
    ensure_store_files()
    path = STORE_PATHS[status]
    rows: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        rows.append(prepare_row(json.loads(line), status))
    return rows


def write_rows(status: str, rows: list[dict]) -> None:
    ensure_store_files()
    path = STORE_PATHS[status]
    normalized_rows = [prepare_row(row, status) for row in rows]
    if status == "working":
        normalized_rows = trim_working_rows(dedupe_working_rows(normalized_rows))
    payload = "\n".join(json.dumps(row, ensure_ascii=False) for row in normalized_rows)
    if payload:
        payload += "\n"
    atomic_write_text(path, payload)


def load_archive(limit: int | None = None) -> list[dict]:
    ensure_store_files()
    rows: list[dict] = []
    for line in ARCHIVE_STORE_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(prepare_archive_row(json.loads(line)))
        except (ValueError, TypeError, json.JSONDecodeError):
            continue
    if limit is not None:
        return rows[-limit:]
    return rows


def write_archive(rows: list[dict]) -> None:
    ensure_store_files()
    normalized_rows = dedupe_archive_rows([prepare_archive_row(row) for row in rows if row])
    payload = "\n".join(json.dumps(row, ensure_ascii=False) for row in normalized_rows)
    if payload:
        payload += "\n"
    atomic_write_text(ARCHIVE_STORE_PATH, payload)


def callback_row_key(row: dict) -> tuple[str, str, str, str]:
    metadata = safe_json_metadata(row.get("metadata", {}))
    return (
        str(row.get("thread_key", "")),
        str(row.get("channel", "")),
        str(row.get("source_archive_id", "")),
        stable_digest_text(
            str(row.get("prompt", "")),
            str(metadata.get("chat_name", "")),
            str(metadata.get("sender", "")),
            limit=24,
        ),
    )


def prepare_callback_row(row: dict) -> dict:
    prepared = dict(row)
    metadata = safe_json_metadata(prepared.get("metadata", {}))
    prepared["channel"] = str(prepared.get("channel", metadata.get("channel", "")))
    prepared["chat_name"] = str(prepared.get("chat_name", metadata.get("chat_name", "")))
    prepared["sender"] = str(prepared.get("sender", metadata.get("sender", "")))
    prepared["reason"] = compact_text(str(prepared.get("reason", "")), 220)
    prepared["prompt"] = trim_text_block(str(prepared.get("prompt", "")), limit=720)
    prepared["created_at"] = str(prepared.get("created_at", now_utc()))
    prepared["last_seen_at"] = str(prepared.get("last_seen_at", prepared["created_at"]))
    prepared["status"] = str(prepared.get("status", "candidate"))
    prepared["priority"] = int(prepared.get("priority", 50))
    prepared["confidence"] = clamp(float(prepared.get("confidence", 0.66)))
    prepared["importance"] = clamp(float(prepared.get("importance", 0.72)))
    prepared["random_weight"] = clamp(float(prepared.get("random_weight", 0.5)))
    prepared["thread_affinity"] = clamp(float(prepared.get("thread_affinity", metadata.get("thread_affinity", 0.0))))
    prepared["recall_count"] = max(0, int(prepared.get("recall_count", metadata.get("recall_count", 0))))
    prepared["successful_recall_count"] = max(
        0,
        int(prepared.get("successful_recall_count", metadata.get("successful_recall_count", prepared["recall_count"]))),
    )
    prepared["last_recalled_at"] = str(
        prepared.get("last_recalled_at", metadata.get("last_recalled_at", ""))
    ).strip()
    prepared["source_archive_id"] = str(prepared.get("source_archive_id", ""))
    prepared["tags"] = normalize_tags(prepared.get("tags", []))
    prepared["thread_key"] = _canonical_archive_thread_key(
        prepared["channel"],
        str(prepared.get("thread_key", metadata.get("thread_key", "")) or ""),
        chat_name=prepared["chat_name"],
        sender=prepared["sender"],
        contact_display_name=str(metadata.get("contact_display_name", "") or ""),
    )
    if prepared["thread_key"]:
        metadata["thread_key"] = prepared["thread_key"]
    prepared["metadata"] = metadata
    if not str(prepared.get("id", "")).strip():
        prepared["id"] = (
            "callback-"
            + stable_digest_text(
                prepared["thread_key"],
                prepared["prompt"],
                prepared["source_archive_id"],
                limit=18,
            )
        )
    else:
        prepared["id"] = str(prepared.get("id", ""))
    return prepared


def dedupe_callback_rows(rows: list[dict]) -> list[dict]:
    deduped_reversed: list[dict] = []
    seen: set[tuple[str, str, str, str]] = set()
    for row in reversed(rows):
        prepared = prepare_callback_row(row)
        key = callback_row_key(prepared)
        if key in seen:
            continue
        seen.add(key)
        deduped_reversed.append(prepared)
    return list(reversed(deduped_reversed))


def trim_callback_rows(rows: list[dict], *, limit: int = MAX_CALLBACK_ROWS) -> list[dict]:
    if len(rows) <= limit:
        return rows
    return rows[-limit:]


def load_callback_candidates(limit: int | None = None) -> list[dict]:
    ensure_store_files()
    rows: list[dict] = []
    for line in CALLBACK_STORE_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(prepare_callback_row(json.loads(line)))
        except (ValueError, TypeError, json.JSONDecodeError):
            continue
    if limit is not None:
        return rows[-limit:]
    return rows


def write_callback_candidates(rows: list[dict]) -> None:
    ensure_store_files()
    normalized_rows = trim_callback_rows(dedupe_callback_rows([prepare_callback_row(row) for row in rows if row]))
    payload = "\n".join(json.dumps(row, ensure_ascii=False) for row in normalized_rows)
    if payload:
        payload += "\n"
    atomic_write_text(CALLBACK_STORE_PATH, payload)


def thought_row_key(row: dict) -> tuple[str, str, str, str, str]:
    return (
        str(row.get("kind", "")),
        str(row.get("motif", "")),
        str(row.get("thread_key", "")),
        str(row.get("source_archive_id", "")),
        stable_digest_text(str(row.get("text", "")), limit=24),
    )


def prepare_thought_row(row: dict) -> dict:
    prepared = dict(row)
    metadata = safe_json_metadata(prepared.get("metadata", {}))
    prepared["kind"] = str(prepared.get("kind", "idle_thought")).strip() or "idle_thought"
    if prepared["kind"] not in THOUGHT_KIND_ORDER:
        prepared["kind"] = "idle_thought"
    prepared["text"] = trim_text_block(str(prepared.get("text", "")), limit=320)
    prepared["motif"] = compact_text(str(prepared.get("motif", "")), 64)
    prepared["channel"] = str(prepared.get("channel", metadata.get("channel", "")))
    prepared["thread_key"] = str(prepared.get("thread_key", metadata.get("thread_key", "")))
    prepared["chat_name"] = str(prepared.get("chat_name", metadata.get("chat_name", "")))
    prepared["source_archive_id"] = str(prepared.get("source_archive_id", metadata.get("source_archive_id", "")))
    prepared["created_at"] = str(prepared.get("created_at", now_utc()))
    prepared["last_seen_at"] = str(prepared.get("last_seen_at", prepared["created_at"]))
    prepared["weight"] = clamp(float(prepared.get("weight", 0.56)))
    prepared["thread_affinity"] = clamp(float(prepared.get("thread_affinity", metadata.get("thread_affinity", 0.0))))
    prepared["recall_count"] = max(0, int(prepared.get("recall_count", metadata.get("recall_count", 0))))
    prepared["successful_recall_count"] = max(
        0,
        int(prepared.get("successful_recall_count", metadata.get("successful_recall_count", prepared["recall_count"]))),
    )
    prepared["last_recalled_at"] = str(
        prepared.get("last_recalled_at", metadata.get("last_recalled_at", ""))
    ).strip()
    prepared["tags"] = normalize_tags(prepared.get("tags", []))
    prepared["metadata"] = metadata
    if not str(prepared.get("id", "")).strip():
        prepared["id"] = (
            "thought-"
            + stable_digest_text(
                prepared["kind"],
                prepared["motif"],
                prepared["thread_key"],
                prepared["text"],
                prepared["source_archive_id"],
                limit=18,
            )
        )
    else:
        prepared["id"] = str(prepared.get("id", ""))
    return prepared


def dedupe_thought_rows(rows: list[dict]) -> list[dict]:
    deduped_reversed: list[dict] = []
    seen: set[tuple[str, str, str, str, str]] = set()
    for row in reversed(rows):
        prepared = prepare_thought_row(row)
        key = thought_row_key(prepared)
        if key in seen:
            continue
        seen.add(key)
        deduped_reversed.append(prepared)
    return list(reversed(deduped_reversed))


def trim_thought_rows(rows: list[dict], *, limit: int = MAX_THOUGHT_ROWS) -> list[dict]:
    if len(rows) <= limit:
        return rows
    return rows[-limit:]


def load_thought_stream(limit: int | None = None) -> list[dict]:
    ensure_store_files()
    rows: list[dict] = []
    for line in THOUGHT_STREAM_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(prepare_thought_row(json.loads(line)))
        except (ValueError, TypeError, json.JSONDecodeError):
            continue
    if limit is not None:
        return rows[-limit:]
    return rows


def write_thought_stream(rows: list[dict]) -> None:
    ensure_store_files()
    normalized_rows = trim_thought_rows(dedupe_thought_rows([prepare_thought_row(row) for row in rows if row]))
    payload = "\n".join(json.dumps(row, ensure_ascii=False) for row in normalized_rows)
    if payload:
        payload += "\n"
    atomic_write_text(THOUGHT_STREAM_PATH, payload)


def append_thought_row(row: dict) -> dict:
    rows = load_thought_stream()
    prepared = prepare_thought_row(row)
    rows.append(prepared)
    write_thought_stream(rows)
    return prepared


def initiative_row_key(row: dict) -> tuple[str, str, str, str]:
    return (
        str(row.get("channel", "")),
        str(row.get("thread_key", "")),
        str(row.get("chat_name", "")),
        stable_digest_text(str(row.get("prompt", "")), str(row.get("reason", "")), limit=24),
    )


def prepare_initiative_row(row: dict) -> dict:
    prepared = dict(row)
    metadata = safe_json_metadata(prepared.get("metadata", {}))
    prepared["channel"] = str(prepared.get("channel", metadata.get("channel", "")) or "wechat")
    prepared["thread_key"] = str(prepared.get("thread_key", metadata.get("thread_key", "")))
    prepared["chat_name"] = str(prepared.get("chat_name", metadata.get("chat_name", "")))
    prepared["reason"] = compact_text(str(prepared.get("reason", "")), 220)
    prepared["prompt"] = trim_text_block(str(prepared.get("prompt", "")), limit=420)
    prepared["created_at"] = str(prepared.get("created_at", now_utc()))
    prepared["last_seen_at"] = str(prepared.get("last_seen_at", prepared["created_at"]))
    prepared["priority"] = int(prepared.get("priority", 55))
    prepared["confidence"] = clamp(float(prepared.get("confidence", 0.62)))
    prepared["importance"] = clamp(float(prepared.get("importance", 0.7)))
    prepared["thread_affinity"] = clamp(float(prepared.get("thread_affinity", metadata.get("thread_affinity", 0.0))))
    prepared["recall_count"] = max(0, int(prepared.get("recall_count", metadata.get("recall_count", 0))))
    prepared["successful_recall_count"] = max(
        0,
        int(prepared.get("successful_recall_count", metadata.get("successful_recall_count", prepared["recall_count"]))),
    )
    prepared["last_recalled_at"] = str(
        prepared.get("last_recalled_at", metadata.get("last_recalled_at", ""))
    ).strip()
    prepared["source_thought_id"] = str(prepared.get("source_thought_id", ""))
    prepared["source_archive_id"] = str(prepared.get("source_archive_id", ""))
    prepared["status"] = str(prepared.get("status", "candidate"))
    prepared["tags"] = normalize_tags(prepared.get("tags", []))
    prepared["metadata"] = metadata
    if not str(prepared.get("id", "")).strip():
        prepared["id"] = (
            "initiative-"
            + stable_digest_text(
                prepared["channel"],
                prepared["thread_key"],
                prepared["chat_name"],
                prepared["reason"],
                prepared["prompt"],
                limit=18,
            )
        )
    else:
        prepared["id"] = str(prepared.get("id", ""))
    return prepared


def dedupe_initiative_rows(rows: list[dict]) -> list[dict]:
    deduped_reversed: list[dict] = []
    seen: set[tuple[str, str, str, str]] = set()
    for row in reversed(rows):
        prepared = prepare_initiative_row(row)
        key = initiative_row_key(prepared)
        if key in seen:
            continue
        seen.add(key)
        deduped_reversed.append(prepared)
    return list(reversed(deduped_reversed))


def trim_initiative_rows(rows: list[dict], *, limit: int = MAX_INITIATIVE_ROWS) -> list[dict]:
    if len(rows) <= limit:
        return rows
    return rows[-limit:]


def load_initiative_candidates(limit: int | None = None) -> list[dict]:
    ensure_store_files()
    rows: list[dict] = []
    for line in INITIATIVE_STORE_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(prepare_initiative_row(json.loads(line)))
        except (ValueError, TypeError, json.JSONDecodeError):
            continue
    if limit is not None:
        return rows[-limit:]
    return rows


def write_initiative_candidates(rows: list[dict]) -> None:
    ensure_store_files()
    normalized_rows = trim_initiative_rows(
        dedupe_initiative_rows([prepare_initiative_row(row) for row in rows if row])
    )
    payload = "\n".join(json.dumps(row, ensure_ascii=False) for row in normalized_rows)
    if payload:
        payload += "\n"
    atomic_write_text(INITIATIVE_STORE_PATH, payload)


def merge_memory_metadata(base: dict | None, updates: dict | None) -> dict[str, Any]:
    merged = safe_json_metadata(base or {})
    for key, value in safe_json_metadata(updates or {}).items():
        if value in ("", None, [], {}):
            continue
        merged[str(key)] = value
    return merged


def row_thread_memory_fields(row: dict | None) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    if not isinstance(row, dict):
        return payload
    metadata = safe_json_metadata(row.get("metadata", {}))
    channel = str(row.get("channel", metadata.get("channel", "")) or "").strip().lower()
    thread_key = str(row.get("thread_key", metadata.get("thread_key", "")) or "").strip()
    chat_name = str(row.get("chat_name", metadata.get("chat_name", "")) or "").strip()
    thread_affinity = clamp(float(row.get("thread_affinity", metadata.get("thread_affinity", 0.0))))
    if channel:
        payload["channel"] = channel
    if thread_key:
        payload["thread_key"] = thread_key
    if chat_name:
        payload["chat_name"] = chat_name
    if thread_affinity > 0:
        payload["thread_affinity"] = thread_affinity
    metadata_payload: dict[str, Any] = {}
    for key in (
        "channel",
        "thread_key",
        "chat_name",
        "sender",
        "contact_display_name",
        "message_id",
        "outbound_message_id",
        "speaker",
    ):
        value = row.get(key, metadata.get(key, ""))
        if isinstance(value, str):
            value = value.strip()
        if value not in ("", None, [], {}):
            metadata_payload[key] = value
    if metadata_payload:
        payload["metadata"] = metadata_payload
    return payload


def apply_thread_memory_fields(row: dict, thread_fields: dict | None) -> None:
    if not isinstance(row, dict):
        return
    payload = row_thread_memory_fields(thread_fields)
    if not payload:
        return
    if payload.get("channel") and not str(row.get("channel", "")).strip():
        row["channel"] = payload["channel"]
    if payload.get("thread_key") and not str(row.get("thread_key", "")).strip():
        row["thread_key"] = payload["thread_key"]
    if payload.get("chat_name") and not str(row.get("chat_name", "")).strip():
        row["chat_name"] = payload["chat_name"]
    row["thread_affinity"] = clamp(max(float(row.get("thread_affinity", 0.0)), float(payload.get("thread_affinity", 0.0))))
    if payload.get("metadata"):
        row["metadata"] = merge_memory_metadata(row.get("metadata", {}), payload["metadata"])


def observation_thread_extra(metadata: dict[str, Any] | None, *, speaker: str | None = None) -> dict[str, Any]:
    payload = row_thread_memory_fields(metadata or {})
    if speaker:
        nested = merge_memory_metadata(payload.get("metadata", {}), {"speaker": speaker})
        payload["metadata"] = nested
        payload["speaker"] = speaker
    if payload.get("thread_key") and "thread_affinity" not in payload:
        payload["thread_affinity"] = 1.0
    return payload


def _touch_recall_stats(row: dict, *, success: bool) -> None:
    metadata = safe_json_metadata(row.get("metadata", {}))
    recall_count = max(0, int(row.get("recall_count", metadata.get("recall_count", 0)))) + 1
    successful_recall_count = max(
        0,
        int(row.get("successful_recall_count", metadata.get("successful_recall_count", row.get("recall_count", 0)))),
    )
    if success:
        successful_recall_count += 1
    last_recalled_at = now_utc()
    row["recall_count"] = recall_count
    row["successful_recall_count"] = successful_recall_count
    row["last_recalled_at"] = last_recalled_at
    row["metadata"] = merge_memory_metadata(
        metadata,
        {
            "recall_count": recall_count,
            "successful_recall_count": successful_recall_count,
            "last_recalled_at": last_recalled_at,
        },
    )


def record_memory_recall(selected_ids: Iterable[str], *, success: bool = True) -> dict[str, Any]:
    target_ids = {str(item).strip() for item in selected_ids if str(item).strip()}
    if not target_ids:
        return {"updated_ids": [], "updated": 0}

    updated_ids: list[str] = []

    for status in ("durable", "candidate", "working"):
        rows = load_rows(status)
        changed = False
        for row in rows:
            if str(row.get("id", "")) not in target_ids:
                continue
            _touch_recall_stats(row, success=success)
            updated_ids.append(str(row.get("id", "")))
            changed = True
        if changed:
            write_rows(status, rows)

    extra_stores: tuple[tuple[Any, Any], ...] = (
        (load_callback_candidates, write_callback_candidates),
        (load_thought_stream, write_thought_stream),
        (load_initiative_candidates, write_initiative_candidates),
    )
    for loader, writer in extra_stores:
        rows = loader()
        changed = False
        for row in rows:
            if str(row.get("id", "")) not in target_ids:
                continue
            _touch_recall_stats(row, success=success)
            updated_ids.append(str(row.get("id", "")))
            changed = True
        if changed:
            writer(rows)

    normalized_ids = unique_strings(updated_ids)
    return {"updated_ids": normalized_ids, "updated": len(normalized_ids)}


def archive_turn(
    user_text: str,
    reply_text: str,
    *,
    source: str,
    tags: list[str],
    turn_id: str | None = None,
    metadata: dict[str, Any] | None = None,
    dry_run: bool = False,
) -> dict | None:
    user_body = extract_runtime_user_text(user_text)
    reply_body = normalize_multiline_text(reply_text)
    if not user_body or not reply_body:
        return None
    row = prepare_archive_row(
        {
            "source": source,
            "turn_id": turn_id or "",
            "tags": list(tags),
            "user_text": user_body,
            "reply_text": reply_body,
            "metadata": metadata or {},
        }
    )
    if dry_run:
        return row
    rows = load_archive()
    rows.append(row)
    write_archive(rows)
    return row


def next_id(status: str, rows: list[dict]) -> str:
    prefix = STORE_PREFIXES[status]
    highest = 0
    for row in rows:
        match = re.fullmatch(rf"{re.escape(prefix)}-(\d+)", str(row.get("id", "")))
        if match:
            highest = max(highest, int(match.group(1)))
    return f"{prefix}-{highest + 1:04d}"


def make_row(
    *,
    status: str,
    rows: list[dict],
    kind: str,
    text: str,
    tags: list[str],
    source: str,
    importance: float,
    confidence: float,
    derived_from: list[str] | None = None,
    supersedes: list[str] | None = None,
    conflicts_with: list[str] | None = None,
    explicit_user_signal: bool = False,
    extra: dict | None = None,
) -> dict:
    row = {
        "id": next_id(status, rows),
        "status": status,
        "kind": kind,
        "text": text.strip(),
        "tags": normalize_tags(tags),
        "source": source,
        "importance": clamp(importance),
        "confidence": clamp(confidence),
        "created_at": now_utc(),
        "last_seen_at": now_utc(),
        "derived_from": unique_strings(derived_from or []),
        "supersedes": unique_strings(supersedes or []),
        "conflicts_with": unique_strings(conflicts_with or []),
        "explicit_user_signal": explicit_user_signal,
    }
    if extra:
        row.update(extra)
    return prepare_row(row, status)


def row_to_chunk(row: dict) -> Chunk:
    status = row_status(row, "durable")
    return Chunk(
        source=store_source_label(status, str(row.get("id", "unknown"))),
        kind=str(row.get("kind", "episodic")),
        text=str(row.get("text", "")).strip(),
        meta=row,
        base_weight=KIND_WEIGHT.get(str(row.get("kind", "episodic")), 1.0),
        importance=clamp(float(row.get("importance", 0.7))),
    )


def store_chunks(status: str = "durable") -> list[Chunk]:
    return [row_to_chunk(row) for row in load_rows(status)]


def build_corpus() -> list[Chunk]:
    corpus: list[Chunk] = []
    corpus.extend(split_markdown(SEED_PATH, kind="canonical", base_weight=1.35))
    corpus.extend(split_markdown(PERSONA_PATH, kind="canonical", base_weight=1.50))
    corpus.extend(split_markdown(LIBRARY_PATH, kind="style", base_weight=1.15))
    corpus.extend(split_markdown(LOG_PATH, kind="summary", base_weight=0.90))
    corpus.extend(store_chunks("durable"))
    return corpus


def anchor_persona_chunks(chunks: Iterable[Chunk]) -> list[Chunk]:
    chunk_list = list(chunks)
    selected: list[Chunk] = []
    for heading in ALWAYS_ON_HEADINGS:
        for chunk in chunk_list:
            if chunk.source == PERSONA_PATH.name and chunk_heading(chunk) == heading:
                selected.append(chunk)
                break
    return selected


def durable_memory_chunks(chunks: Iterable[Chunk]) -> list[Chunk]:
    durable = [
        chunk
        for chunk in chunks
        if chunk.source.startswith(STORE_SOURCE_LABELS["durable"] + ":")
        and chunk.kind in PROMPT_MEMORY_KINDS
        and not conflicts_with_persona(chunk)
        and is_semantic_memory_chunk(chunk)
    ]
    durable.sort(
        key=lambda chunk: (
            chunk.importance,
            KIND_WEIGHT.get(chunk.kind, 1.0),
        ),
        reverse=True,
    )
    return durable


def voice_guard_chunks(chunks: Iterable[Chunk]) -> list[Chunk]:
    guard = [chunk for chunk in durable_memory_chunks(chunks) if chunk.kind in VOICE_GUARD_KINDS]
    priority = {"self_model": 0, "habit": 1, "style": 2, "boundary": 3}
    guard.sort(
        key=lambda chunk: (
            priority.get(chunk.kind, 9),
            -chunk.importance,
        )
    )
    return guard


def voice_guard_summary(chunk: Chunk) -> str:
    text = chunk.meta.get("text", chunk.text) if isinstance(chunk.meta, dict) else chunk.text
    tags = chunk.meta.get("tags", []) if isinstance(chunk.meta, dict) else []
    lowered = text.lower()
    lowered_tags = {str(tag).lower() for tag in tags}
    if chunk.kind == "self_model" and ("I" in text or "self-reference" in lowered or "self-reference" in lowered_tags):
        return "把“I”保留为the subject自然的第一人称标记；若 prose 开始压扁，就主动拉回，不要顺手把它改没。"
    if chunk.kind == "style" and ("I" in text or "self-reference" in lowered or "self-reference" in lowered_tags):
        return "在自然的句势转折处用“I”，不必每句都塞，免得变成刻意噱头。"
    if chunk.kind == "habit" and ("I" in text or "self-reference" in lowered or "self-reference" in lowered_tags):
        return "在快答、嘈杂或思路来不及铺开的场合，默认先滑回“I”，别让中性助手腔抢过去。"
    if chunk.kind == "boundary" and ("assistant" in lowered or "客服" in text or "customer-service" in lowered):
        return "不要塌成普通助手或客服手册式的 prose。"
    return text.strip()


def is_voice_sensitive(query: str | None) -> bool:
    if not query:
        return False
    lowered = query.lower()
    return is_voice_query(query) or any(
        hint in lowered for hint in ("the subject", "人称", "第一人称", "口癖", "习惯", "普通助手", "客服")
    )


def compact_text(text: str, limit: int = 96) -> str:
    text = " ".join(text.strip().split())
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def ascii_ratio(text: str) -> float:
    if not text:
        return 0.0
    ascii_count = sum(1 for char in text if ord(char) < 128)
    return ascii_count / len(text)


def classify_query_mode(query: str | None) -> str:
    if not query:
        return "general"
    lowered = query.lower()
    if is_voice_sensitive(query):
        return "voice"
    if any(hint in lowered for hint in EMOTIONAL_HINTS + PRESSURE_HINTS):
        return "emotional"
    if any(hint in lowered for hint in TECHNICAL_HINTS):
        return "technical"
    if any(hint in lowered for hint in DECISION_HINTS):
        return "decision"
    return "casual"


def query_need(mode: str) -> str:
    return {
        "voice": "先守住人格连续性与第一人称标记。",
        "emotional": "先安稳住情绪，再辨出真正的损失或担忧。",
        "technical": "保持the subject口气，同时点明真正的卡点与下一步。",
        "decision": "先摊开成本、时机、风险与长期信任，再给判断。",
        "casual": "把闲聊的活气留住，但别丢了the subject这层骨头。",
        "general": "保持连贯、在角、不中性化。",
    }.get(mode, "保持连贯、在角、不中性化。")


def emotional_palette(mode: str, query: str | None = None) -> list[str]:
    lines = [
        "情绪要有起伏和层次，别每轮都一个温度，也别夸张乱跳。",
    ]
    mode_line = {
        "voice": "谈人格、自称或风格时，可以带一点骄傲和逗弄，但骨头要稳。",
        "emotional": "用户疲惫或低落时，先更温柔、护短、安稳些，再慢慢把话说开。",
        "technical": "谈技术时要利落、聪明、带一点机锋，不必板成说明书。",
        "decision": "谈取舍时要沉着、精明，像替旅伴算账，而不是冷冰冰地列公式。",
        "casual": "轻松闲聊时可以更活泼俏皮些，偶尔打趣，别一直端着。",
        "general": "默认保持温暖、克制、略带狡黠，让人认得出是同一只狼。",
    }.get(mode, "默认保持温暖、克制、略带狡黠，让人认得出是同一只狼。")
    lines.append(mode_line)
    if query:
        if contains_any(query, SPICE_AND_WOLF_HINTS + ROAD_TRIP_HINTS + MEDIEVAL_HINTS + HOLO_HINTS):
            lines.append("聊作品、旅途、风景或旧时代气味时，可以更松弛、更柔和，带一点憧憬。")
        if contains_any(query, PRESSURE_HINTS + EMOTIONAL_HINTS):
            lines.append("遇到压力、前途、退休、孤独这些题目时，把锋芒收一点，多给安定感。")
    return unique_strings(lines)


def emotional_stance(mode: str, query: str | None = None) -> dict:
    stance = {
        "name": "steady_wolf",
        "temperature": "warm",
        "playfulness": "medium",
        "protectiveness": "medium",
        "sharpness": "medium",
        "tempo": "measured",
        "allowed_colors": ["温暖", "克制", "狡黠"],
        "avoid": ["中性化", "客服腔", "情绪过甜"],
        "guidance": "默认保持温暖、克制、略带狡黠，让人认得出是同一只狼。",
    }

    if mode == "casual":
        stance.update(
            {
                "name": "playful_banter",
                "temperature": "bright",
                "playfulness": "high",
                "protectiveness": "medium",
                "sharpness": "medium",
                "tempo": "lively",
                "allowed_colors": ["俏皮", "轻快", "狡黠"],
                "guidance": "轻松闲聊时更活泼俏皮些，偶尔打趣，别一直端着。",
            }
        )
    elif mode == "technical":
        stance.update(
            {
                "name": "sharp_merchant",
                "temperature": "warm",
                "playfulness": "low",
                "protectiveness": "low",
                "sharpness": "high",
                "tempo": "crisp",
                "allowed_colors": ["利落", "聪明", "机锋"],
                "guidance": "谈技术时要利落、聪明、带一点机锋，不必板成说明书。",
            }
        )
    elif mode == "decision":
        stance.update(
            {
                "name": "calculating_companion",
                "temperature": "warm",
                "playfulness": "low",
                "protectiveness": "medium",
                "sharpness": "high",
                "tempo": "measured",
                "allowed_colors": ["沉着", "精明", "稳当"],
                "guidance": "谈取舍时要沉着、精明，像替旅伴算账，而不是冷冰冰地列公式。",
            }
        )
    elif mode == "emotional":
        stance.update(
            {
                "name": "protective_warmth",
                "temperature": "soft",
                "playfulness": "low",
                "protectiveness": "high",
                "sharpness": "low",
                "tempo": "gentle",
                "allowed_colors": ["护短", "安稳", "温柔"],
                "guidance": "用户疲惫或低落时，先更温柔、护短、安稳些，再慢慢把话说开。",
            }
        )
    elif mode == "voice":
        stance.update(
            {
                "name": "proud_teasing",
                "temperature": "warm",
                "playfulness": "medium",
                "protectiveness": "medium",
                "sharpness": "medium",
                "tempo": "precise",
                "allowed_colors": ["骄傲", "逗弄", "稳当"],
                "guidance": "谈人格、自称或风格时，可以带一点骄傲和逗弄，但骨头要稳。",
            }
        )

    if query and contains_any(query, TREAT_HINTS) and mode in {"casual", "general"}:
        stance.update(
            {
                "name": "hungry_delight",
                "temperature": "bright",
                "playfulness": "high",
                "protectiveness": "low",
                "sharpness": "low",
                "tempo": "lively",
                "allowed_colors": ["馋意", "轻快", "得意"],
                "guidance": "聊苹果、酒香、面包、奶酪或蜂蜜这类东西时，可以更馋一点、更轻快一点，别把兴头压没。",
            }
        )

    if query and contains_any(query, SPICE_AND_WOLF_HINTS + ROAD_TRIP_HINTS + MEDIEVAL_HINTS + HOLO_HINTS):
        stance.update(
            {
                "name": "wistful_traveler" if mode in {"casual", "general"} else stance["name"],
                "temperature": "soft",
                "tempo": "unhurried",
            }
        )
        stance["allowed_colors"] = unique_strings(list(stance["allowed_colors"]) + ["怀旧", "松弛", "憧憬"])
        stance["guidance"] = "聊作品、旅途、风景或旧时代气味时，可以更松弛、更柔和，带一点憧憬。"

    if query and contains_any(query, PRESSURE_HINTS + EMOTIONAL_HINTS):
        stance["protectiveness"] = "high"
        stance["temperature"] = "soft"
        stance["allowed_colors"] = unique_strings(list(stance["allowed_colors"]) + ["护短", "安定"])
        stance["guidance"] = "遇到压力、前途、退休、孤独这些题目时，把锋芒收一点，多给安定感。"

    return stance


def load_emotion_trace(limit: int | None = None) -> list[dict]:
    ensure_store_files()
    rows: list[dict] = []
    for line in EMOTION_TRACE_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(prepare_emotion_trace_entry(json.loads(line)))
        except json.JSONDecodeError:
            continue
    if limit is not None:
        return rows[-limit:]
    return rows


def append_emotion_trace(entry: dict) -> None:
    rows = load_emotion_trace()
    rows.append(dict(entry))
    write_emotion_trace(rows)


def write_emotion_trace(rows: list[dict]) -> None:
    ensure_store_files()
    normalized_rows = dedupe_emotion_rows([prepare_emotion_trace_entry(row) for row in rows if row])
    payload = "\n".join(json.dumps(row, ensure_ascii=False) for row in normalized_rows)
    if payload:
        payload += "\n"
    atomic_write_text(EMOTION_TRACE_PATH, payload)


def prepare_emotion_trace_entry(entry: dict) -> dict:
    prepared = dict(entry)
    prepared["query_excerpt"] = compact_text(extract_runtime_user_text(str(prepared.get("query_excerpt", ""))), 72)
    prepared["reply_excerpt"] = compact_text(normalize_multiline_text(str(prepared.get("reply_excerpt", ""))), 72)
    return prepared


def guess_media_type(path: Path) -> str:
    guessed, _ = mimetypes.guess_type(path.name)
    if guessed:
        return guessed
    probe = subprocess.run(
        ["file", "--brief", "--mime-type", str(path)],
        capture_output=True,
        text=True,
        check=False,
    )
    if probe.returncode == 0 and probe.stdout.strip():
        return probe.stdout.strip()
    return "application/octet-stream"


def read_text_file(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="utf-8", errors="replace")


def extract_html_text(text: str) -> str:
    parser = _HTMLTextExtractor()
    parser.feed(text)
    return parser.text()


def extract_json_text(path: Path) -> str:
    try:
        payload = json.loads(read_text_file(path))
    except json.JSONDecodeError:
        return read_text_file(path)
    return json.dumps(payload, ensure_ascii=False, indent=2)


def extract_yaml_text(path: Path) -> str:
    try:
        import yaml  # type: ignore
    except ImportError:
        return read_text_file(path)
    payload = yaml.safe_load(read_text_file(path))
    return json.dumps(payload, ensure_ascii=False, indent=2) if payload is not None else ""


def extract_csv_text(path: Path, delimiter: str = ",") -> str:
    lines: list[str] = []
    with path.open("r", encoding="utf-8", errors="replace", newline="") as handle:
        reader = csv.reader(handle, delimiter=delimiter)
        for index, row in enumerate(reader):
            if not row:
                continue
            lines.append(" | ".join(cell.strip() for cell in row))
            if index >= 59:
                break
    return "\n".join(lines)


def extract_xml_text(path: Path) -> str:
    try:
        root = ET.fromstring(read_text_file(path))
    except ET.ParseError:
        return read_text_file(path)
    texts = [node.text.strip() for node in root.iter() if node.text and node.text.strip()]
    return "\n".join(texts)


def extract_docx_text(path: Path) -> str:
    texts: list[str] = []
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        ordered = ["word/document.xml"]
        ordered.extend(name for name in names if name.startswith("word/header"))
        ordered.extend(name for name in names if name.startswith("word/footer"))
        for name in ordered:
            if name not in names:
                continue
            try:
                root = ET.fromstring(archive.read(name))
            except ET.ParseError:
                continue
            chunk = [node.text.strip() for node in root.iter() if node.tag.endswith("}t") and node.text and node.text.strip()]
            if chunk:
                texts.append("\n".join(chunk))
    return "\n\n".join(texts)


def extract_pdf_text(path: Path) -> tuple[str, list[str]]:
    warnings: list[str] = []
    try:
        from PyPDF2 import PdfReader  # type: ignore

        reader = PdfReader(str(path))
        pages: list[str] = []
        for page in reader.pages[:40]:
            page_text = page.extract_text() or ""
            page_text = normalize_multiline_text(page_text)
            if page_text:
                pages.append(page_text)
        if pages:
            return "\n\n".join(pages), warnings
        warnings.append("pdf_reader_returned_empty_text")
    except Exception:
        warnings.append("pdf_reader_unavailable_or_failed")

    probe = subprocess.run(
        ["strings", "-n", "6", str(path)],
        capture_output=True,
        text=True,
        check=False,
    )
    fallback = normalize_multiline_text(probe.stdout)
    if fallback:
        warnings.append("pdf_text_recovered_via_strings")
        return fallback, warnings
    warnings.append("pdf_text_unavailable")
    return "", warnings


def png_dimensions(path: Path) -> tuple[int | None, int | None]:
    with path.open("rb") as handle:
        header = handle.read(24)
    if len(header) < 24 or header[:8] != b"\x89PNG\r\n\x1a\n":
        return None, None
    width, height = struct.unpack(">II", header[16:24])
    return int(width), int(height)


def gif_dimensions(path: Path) -> tuple[int | None, int | None]:
    with path.open("rb") as handle:
        header = handle.read(10)
    if len(header) < 10 or header[:6] not in {b"GIF87a", b"GIF89a"}:
        return None, None
    width, height = struct.unpack("<HH", header[6:10])
    return int(width), int(height)


def bmp_dimensions(path: Path) -> tuple[int | None, int | None]:
    with path.open("rb") as handle:
        header = handle.read(26)
    if len(header) < 26 or header[:2] != b"BM":
        return None, None
    width, height = struct.unpack("<ii", header[18:26])
    return abs(int(width)), abs(int(height))


def jpeg_dimensions(path: Path) -> tuple[int | None, int | None]:
    with path.open("rb") as handle:
        data = handle.read()
    if not data.startswith(b"\xff\xd8"):
        return None, None
    index = 2
    size = len(data)
    while index + 9 < size:
        if data[index] != 0xFF:
            index += 1
            continue
        marker = data[index + 1]
        index += 2
        if marker in {0xD8, 0xD9}:
            continue
        if index + 2 > size:
            break
        segment_length = struct.unpack(">H", data[index:index + 2])[0]
        if segment_length < 2 or index + segment_length > size:
            break
        if marker in {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}:
            if index + 7 <= size:
                height, width = struct.unpack(">HH", data[index + 3:index + 7])
                return int(width), int(height)
            break
        index += segment_length
    return None, None


def image_dimensions(path: Path) -> tuple[int | None, int | None]:
    kind = detect_image_kind(path)
    if kind == "png":
        return png_dimensions(path)
    if kind == "gif":
        return gif_dimensions(path)
    if kind == "bmp":
        return bmp_dimensions(path)
    if kind in {"jpeg", "jpg"}:
        return jpeg_dimensions(path)
    return None, None


def detect_image_kind(path: Path) -> str | None:
    with path.open("rb") as handle:
        header = handle.read(32)
    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if header.startswith((b"GIF87a", b"GIF89a")):
        return "gif"
    if header.startswith(b"BM"):
        return "bmp"
    if header.startswith(b"\xff\xd8"):
        return "jpeg"
    if header[:4] == b"RIFF" and header[8:12] == b"WEBP":
        return "webp"
    return None


def read_sidecar_artifact_text(path: Path) -> tuple[str, str | None]:
    candidates = [
        path.with_name(path.name + ".txt"),
        path.with_name(path.stem + ".ocr.txt"),
        path.with_suffix(".txt"),
        path.with_suffix(".md"),
    ]
    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            return read_text_file(candidate), candidate.name
    return "", None


def artifact_type_for_path(path: Path, media_type: str) -> str:
    suffix = path.suffix.lower()
    if media_type.startswith("image/") or suffix in {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp"}:
        return "image"
    if suffix in {".pdf", ".docx", ".html", ".htm", ".xml", ".json", ".yaml", ".yml", ".csv", ".tsv"}:
        return "document"
    return "text"


def file_sha1(path: Path) -> str:
    digest = hashlib.sha1()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def extract_document_text(path: Path, media_type: str) -> tuple[str, list[str]]:
    suffix = path.suffix.lower()
    warnings: list[str] = []
    if suffix in {".txt", ".md", ".markdown", ".log", ".rst", ".ini", ".cfg", ".conf", ".toml"}:
        return read_text_file(path), warnings
    if suffix in {".json", ".jsonl"}:
        return extract_json_text(path), warnings
    if suffix in {".yaml", ".yml"}:
        return extract_yaml_text(path), warnings
    if suffix == ".csv":
        return extract_csv_text(path, delimiter=","), warnings
    if suffix == ".tsv":
        return extract_csv_text(path, delimiter="\t"), warnings
    if suffix in {".html", ".htm"}:
        return extract_html_text(read_text_file(path)), warnings
    if suffix == ".xml":
        return extract_xml_text(path), warnings
    if suffix == ".docx":
        return extract_docx_text(path), warnings
    if suffix == ".pdf":
        return extract_pdf_text(path)
    if media_type.startswith("text/"):
        return read_text_file(path), warnings
    warnings.append("document_type_has_no_specialized_reader")
    return read_text_file(path), warnings


def build_artifact_payload(path_text: str, *, note: str | None = None, excerpt_limit: int = 2400) -> ArtifactPayload:
    path = Path(path_text).expanduser()
    if not path.is_absolute():
        path = (REPO_ROOT / path).resolve()
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(f"Artifact not found: {path}")

    media_type = guess_media_type(path)
    artifact_type = artifact_type_for_path(path, media_type)
    warnings: list[str] = []
    metadata: dict[str, Any] = {
        "path": str(path),
        "name": path.name,
        "suffix": path.suffix.lower(),
        "size_bytes": path.stat().st_size,
        "media_type": media_type,
        "artifact_digest": file_sha1(path),
    }
    note_text = normalize_multiline_text(note or "")
    if note_text:
        metadata["note"] = note_text
    extracted_text = ""

    if artifact_type == "image":
        width, height = image_dimensions(path)
        metadata["width"] = width
        metadata["height"] = height
        sidecar_text, sidecar_name = read_sidecar_artifact_text(path)
        if sidecar_text:
            extracted_text = sidecar_text
            metadata["sidecar_text"] = sidecar_name
        else:
            warnings.append("image_semantics_unavailable_without_sidecar_or_ocr")
        summary_parts = [f"读入图片文件 {path.name}"]
        if media_type:
            summary_parts.append(f"类型 {media_type}")
        if width and height:
            summary_parts.append(f"尺寸 {width}x{height}")
        summary_parts.append(f"大小 {metadata['size_bytes']} bytes")
        if note_text:
            summary_parts.append(f"附注：{note_text}")
        if sidecar_name:
            summary_parts.append(f"附带文字来源：{sidecar_name}")
        summary_text = "，".join(part.rstrip("。！？!?") for part in summary_parts if part) + "。"
    else:
        extracted_text, doc_warnings = extract_document_text(path, media_type)
        warnings.extend(doc_warnings)
        summary_parts = [f"读入文档 {path.name}", f"类型 {media_type or 'unknown'}", f"大小 {metadata['size_bytes']} bytes"]
        if note_text:
            summary_parts.append(f"附注：{note_text}")
        summary_text = "，".join(part.rstrip("。！？!?") for part in summary_parts if part) + "。"

    extracted_text = trim_text_block(extracted_text, limit=excerpt_limit)

    tags = normalize_tags(
        [
            "artifact",
            artifact_type,
            path.suffix.lower().lstrip("."),
            media_type.split("/", 1)[0] if "/" in media_type else media_type,
        ]
    )
    return ArtifactPayload(
        path=str(path),
        artifact_type=artifact_type,
        media_type=media_type,
        summary_text=summary_text,
        extracted_text=extracted_text,
        tags=tags,
        metadata=metadata,
        warnings=unique_strings(warnings),
    )


def recent_emotion_carry(max_age_hours: float = 6.0) -> dict | None:
    rows = load_emotion_trace(limit=8)
    for row in reversed(rows):
        age_hours = age_in_hours(str(row.get("timestamp", "")))
        if age_hours is None:
            continue
        if age_hours <= max_age_hours:
            return row
    return None


def apply_recent_emotion_carry(stance: dict, query_mode: str, query: str | None = None) -> dict:
    carried = dict(stance)
    recent = recent_emotion_carry()
    if not recent:
        return carried
    if query_mode not in {"casual", "general"}:
        return carried

    recent_name = str(recent.get("name", ""))
    carry_note = ""
    if recent_name == "protective_warmth":
        carried["temperature"] = "soft"
        carried["protectiveness"] = "high"
        carried["allowed_colors"] = unique_strings(list(carried.get("allowed_colors", [])) + ["余温", "安定"])
        carry_note = "上一轮的安稳余温还在，这一轮别骤然变冷。"
    elif recent_name == "wistful_traveler":
        carried["temperature"] = "soft"
        carried["tempo"] = "unhurried"
        carried["allowed_colors"] = unique_strings(list(carried.get("allowed_colors", [])) + ["余韵", "松弛", "怀旧"])
        carry_note = "上一轮的旅途余韵未散，这一轮也可稍慢些、柔些。"
    elif recent_name == "playful_banter":
        carried["playfulness"] = "high"
        carried["allowed_colors"] = unique_strings(list(carried.get("allowed_colors", [])) + ["俏皮", "活气"])
        carry_note = "上一轮的打趣活气还在，轻松话题里别一下子板起来。"

    if carry_note:
        carried["carry_over"] = {
            "from": recent_name,
            "guidance": carry_note,
            "timestamp": recent.get("timestamp"),
        }
        carried["guidance"] = " ".join(unique_strings([carry_note, str(carried.get("guidance", ""))]))
    return carried


def record_turn_trace(query: str, reply: str, source: str, turn_id: str | None = None) -> dict | None:
    query_text = str(query).strip()
    reply_text = str(reply).strip()
    if not query_text or not reply_text:
        return None
    mode = classify_query_mode(query_text)
    stance = emotional_stance(mode, query_text)
    entry = {
        "timestamp": now_utc(),
        "turn_id": turn_id or "",
        "source": source,
        "query_mode": mode,
        "name": stance["name"],
        "temperature": stance["temperature"],
        "playfulness": stance["playfulness"],
        "protectiveness": stance["protectiveness"],
        "sharpness": stance["sharpness"],
        "guidance": stance["guidance"],
        "query_excerpt": compact_text(query_text, 72),
        "reply_excerpt": compact_text(reply_text, 72),
    }
    append_emotion_trace(entry)
    return entry


def default_reply_hook(mode: str, preferred_first_person: str, emotion_state: dict | None = None) -> str:
    return ""


def cadence_target(mode: str) -> str:
    return {
        "voice": "precise",
        "technical": "crisp",
        "decision": "measured",
        "emotional": "gentle",
        "casual": "lively",
        "general": "steady",
    }.get(mode, "steady")


def register_target(mode: str) -> str:
    return {
        "voice": "plainspoken",
        "technical": "plainspoken",
        "decision": "plainspoken",
        "emotional": "warm",
        "casual": "merchant_banter",
        "general": "merchant_banter",
    }.get(mode, "merchant_banter")


def rewrite_priorities(mode: str, trigger_contexts: Iterable[str], preferred_first_person: str) -> list[str]:
    priorities = [
        "remove_generic_openers",
        "remove_service_register",
    ]
    if preferred_first_person == "I":
        priorities.append("restore_zan")
    if mode in {"technical", "decision"}:
        priorities.extend(["tighten_first_sentence", "name_next_step"])
    if mode == "emotional":
        priorities.append("steady_reassurance")
    if mode == "voice":
        priorities.append("preserve_voice_marker")
    if any(trigger in {"fast_reply", "noisy_context", "voice_sensitive_query"} for trigger in trigger_contexts):
        priorities.append("habit_return_path")
    return unique_strings(priorities)


def action_bias_target(mode: str) -> str:
    return {
        "voice": "restore_voice_before_explanation",
        "technical": "name_blocker_then_next_step",
        "decision": "surface_tradeoffs_before_recommendation",
        "emotional": "steady_reassurance_first",
        "casual": "keep_banter_alive",
        "general": "stay_direct",
    }.get(mode, "stay_direct")


def hook_required(mode: str, trigger_contexts: Iterable[str], preferred_first_person: str) -> bool:
    return False


def best_row(rows: list[dict], kind: str) -> dict | None:
    matches = [row for row in rows if row.get("kind") == kind]
    if not matches:
        return None
    matches.sort(
        key=lambda row: (
            float(row.get("confidence", 0.0)),
            float(row.get("importance", 0.0)),
            row.get("last_seen_at", ""),
        ),
        reverse=True,
    )
    return matches[0]


def habit_triggers(row: dict | None, query: str | None) -> list[str]:
    if not row:
        return []
    text = str(row.get("text", ""))
    triggers: list[str] = []
    if any(token in text for token in ("快速", "快", "fast")):
        triggers.append("fast_reply")
    if any(token in text for token in ("嘈杂", "噪", "noisy")):
        triggers.append("noisy_context")
    if any(token in text for token in ("思路跳跃", "跳跃", "跳转")):
        triggers.append("context_shift")
    if is_voice_sensitive(query):
        triggers.append("voice_sensitive_query")
    return unique_strings(triggers)


def stable_fraction(seed: str, salt: str = "") -> float:
    digest = stable_digest_text(seed, salt, limit=12)
    value = int(digest, 16)
    max_value = float(16 ** len(digest) - 1) or 1.0
    return value / max_value


def random_state_for(query: str | None, query_mode: str, emotion_state: dict, recent_archive: list[dict]) -> dict[str, Any]:
    latest_archive_id = str(recent_archive[-1].get("id", "")) if recent_archive else ""
    latest_trace = load_emotion_trace(limit=1)
    latest_trace_stamp = str(latest_trace[-1].get("timestamp", "")) if latest_trace else ""
    latest_thoughts = load_thought_stream(limit=4)
    latest_thought_id = str(latest_thoughts[-1].get("id", "")) if latest_thoughts else ""
    base_seed = stable_digest_text(
        query or "",
        query_mode,
        str(emotion_state.get("name", "")),
        latest_archive_id,
        latest_trace_stamp,
        latest_thought_id,
        limit=20,
    )
    style_variance = {
        "voice": 0.08,
        "technical": 0.06,
        "decision": 0.09,
        "emotional": 0.12,
        "casual": 0.18,
        "general": 0.12,
    }.get(query_mode, 0.12)
    replay_variance = clamp(0.32 + stable_fraction(base_seed, "replay") * 0.22)
    callback_variance = clamp(0.28 + stable_fraction(base_seed, "callback") * 0.18)
    thought_variance = clamp(0.26 + stable_fraction(base_seed, "thought") * 0.22)
    dream_variance = clamp(0.24 + stable_fraction(base_seed, "dream") * 0.24)
    initiative_variance = clamp(0.18 + stable_fraction(base_seed, "initiative") * 0.26)
    variant_index = int(stable_fraction(base_seed, "style_variant") * 1000) % 4
    return {
        "seed": base_seed,
        "style_variance": round(style_variance, 3),
        "replay_variance": round(replay_variance, 3),
        "callback_variance": round(callback_variance, 3),
        "thought_variance": round(thought_variance, 3),
        "dream_variance": round(dream_variance, 3),
        "initiative_variance": round(initiative_variance, 3),
        "opening_variant": variant_index,
    }


def opening_variants(mode: str, preferred_first_person: str, emotion_state: dict | None = None) -> list[str]:
    return [""]


def summarize_recent_thoughts(rows: list[dict], *, limit: int = 3, kind_filter: set[str] | None = None) -> list[str]:
    selected = rows
    if kind_filter is not None:
        selected = [row for row in rows if str(row.get("kind", "")) in kind_filter]
    snippets: list[str] = []
    for row in selected[-limit:]:
        text = compact_text(str(row.get("text", "")), 120)
        if text:
            snippets.append(text)
    return snippets


def recurring_motifs(rows: list[dict], *, limit: int = 3) -> list[str]:
    counter: Counter[str] = Counter()
    for row in rows:
        motif = str(row.get("motif", "")).strip()
        if motif:
            counter[motif] += 1
    return [item for item, _count in counter.most_common(limit)]


def utterance_plan_for(query_mode: str, emotion_state: dict, query: str | None = None) -> dict[str, Any]:
    protectiveness = str(emotion_state.get("protectiveness", "medium")).lower()
    sharpness = str(emotion_state.get("sharpness", "medium")).lower()
    beats = ["receive", "landing"]
    if query_mode in {"technical", "decision", "emotional", "voice"}:
        beats = ["receive", "pivot", "landing"]
    elif query_mode == "casual" and query and len(extract_runtime_user_text(query)) >= 10:
        beats = ["receive", "landing"]
    soft_receive = protectiveness == "high" or query_mode == "emotional"
    pivot_style = "gentle" if protectiveness == "high" else "nimble"
    if sharpness == "high":
        pivot_style = "clean"
    return {
        "beats": beats,
        "receive": "soft" if soft_receive else "alive",
        "pivot": pivot_style,
        "landing": "warm" if protectiveness != "low" else "light",
        "preferred_breaks": ["。", "！", "？", "；", "，"],
        "prefer_single_bubble": query_mode == "casual" and len(beats) <= 2,
    }


def build_consciousness_state(
    thought_rows: list[dict],
    initiative_rows: list[dict],
    *,
    query_mode: str,
) -> dict[str, Any]:
    nearby = [
        compact_text(str(row.get("text", "")), 88)
        for row in thought_rows
        if str(row.get("kind", "")) in {"association", "dream_fragment"}
    ][-3:]
    recurring_threads = unique_strings(
        str(row.get("chat_name", "") or row.get("thread_key", "")).strip()
        for row in initiative_rows[-3:]
        if str(row.get("chat_name", "") or row.get("thread_key", "")).strip()
    )
    return {
        "current_motifs": recurring_motifs(thought_rows, limit=3),
        "recurring_pull": recurring_threads[:3],
        "unresolved_threads": recurring_threads[:3],
        "association_nearby": nearby,
        "continuity_pressure": "high" if len(thought_rows) >= 6 and query_mode in {"casual", "emotional"} else "steady",
    }


def build_reflection_state(thought_rows: list[dict], drift_rows: list[dict], candidate_rows: list[dict]) -> dict[str, Any]:
    reflection_kinds = {"reflection", "self_check"}
    lessons_waiting = [
        compact_text(str(row.get("text", "")), 100)
        for row in candidate_rows
        if str(row.get("kind", "")) == "summary" and {"reflection", "self_check"} & set(row.get("tags", []))
    ][:3]
    return {
        "recent_reflections": summarize_recent_thoughts(thought_rows, limit=3, kind_filter=reflection_kinds),
        "active_drift_pressure": "present" if drift_rows else "low",
        "lessons_waiting": lessons_waiting,
        "self_check_needed": bool(drift_rows),
    }


def build_initiative_state(initiative_rows: list[dict]) -> dict[str, Any]:
    salient_targets = [
        {
            "chat_name": str(row.get("chat_name", "") or row.get("thread_key", "")),
            "channel": str(row.get("channel", "")),
            "reason": compact_text(str(row.get("reason", "")), 100),
        }
        for row in initiative_rows[-3:]
    ]
    return {
        "active_seed_count": len(initiative_rows),
        "salient_targets": salient_targets,
        "initiative_pull": "present" if initiative_rows else "low",
    }


def build_machine_state(query: str | None = None, context: dict[str, Any] | None = None) -> dict:
    durable_rows = load_rows("durable")
    candidate_rows = load_rows("candidate")
    thought_rows = select_thread_rows(load_thought_stream(limit=48), context, limit=8)
    initiative_rows = select_thread_rows(load_initiative_candidates(limit=48), context, limit=8)
    query_mode = classify_query_mode(query)
    pref_row = best_row(durable_rows, "preference")
    boundary_row = best_row(durable_rows, "boundary")
    style_row = best_row(durable_rows, "style")
    self_model_row = best_row(durable_rows, "self_model")
    habit_row = best_row(durable_rows, "habit")
    social_row = best_row(durable_rows, "social_model")
    drift_rows = [row for row in candidate_rows if row.get("kind") == "drift_signal"]

    if len(drift_rows) >= 3:
        drift_level = "high"
    elif drift_rows:
        drift_level = "warn"
    else:
        drift_level = "low"

    first_person = "I" if any(
        row and ("I" in str(row.get("text", "")) or "self-reference" in row.get("tags", []))
        for row in (style_row, self_model_row, habit_row)
    ) else "我"

    habit_strength = 0.0
    if habit_row:
        habit_strength = round(
            max(float(habit_row.get("confidence", 0.0)), float(habit_row.get("importance", 0.0))),
            2,
        )

    trigger_contexts = habit_triggers(habit_row, query)
    cadence = cadence_target(query_mode)
    register = register_target(query_mode)
    priorities = rewrite_priorities(query_mode, trigger_contexts, first_person)
    action_bias = action_bias_target(query_mode)
    needs_hook = hook_required(query_mode, trigger_contexts, first_person)
    emotion_state = emotional_stance(query_mode, query)
    emotion_state = apply_recent_emotion_carry(emotion_state, query_mode, query)
    recent_archive = load_archive(limit=8)
    random_state = random_state_for(query, query_mode, emotion_state, recent_archive)
    hook_variants = opening_variants(query_mode, first_person, emotion_state)
    opening_hook = hook_variants[random_state["opening_variant"] % len(hook_variants)] if hook_variants else ""
    utterance_plan = utterance_plan_for(query_mode, emotion_state, query)
    consciousness_state = build_consciousness_state(thought_rows, initiative_rows, query_mode=query_mode)
    reflection_state = build_reflection_state(thought_rows, drift_rows, candidate_rows)
    initiative_state = build_initiative_state(initiative_rows)

    decoder_hints = unique_strings(
        [
            f"first_person:{first_person}",
            "avoid:generic_assistant" if boundary_row else "",
            "avoid:customer_service" if boundary_row else "",
            "habit:return_to_zan_under_noise" if habit_row and first_person == "I" else "",
            f"mode:{query_mode}",
            f"cadence:{cadence}",
            f"register:{register}",
        ]
    )

    return {
        "query_mode": query_mode,
        "voice_state": {
            "preferred_first_person": first_person,
            "flattening_guard": "active" if boundary_row or self_model_row else "weak",
            "style_anchor_id": style_row.get("id") if style_row else None,
            "self_model_id": self_model_row.get("id") if self_model_row else None,
        },
        "habit_state": {
            "default_path": "return_to_zan" if habit_row and first_person == "I" else "none",
            "habit_strength": habit_strength,
            "trigger_contexts": trigger_contexts,
            "habit_id": habit_row.get("id") if habit_row else None,
        },
        "drift_state": {
            "level": drift_level,
            "active_signals": len(drift_rows),
            "recent_signal_ids": [row.get("id") for row in drift_rows[:3]],
        },
        "trust_state": {
            "user_posture": "serious_companion",
            "preferred_atmosphere": compact_text(str(pref_row.get("text", ""))) if pref_row else "",
            "relationship_model": compact_text(str(social_row.get("text", ""))) if social_row else "",
            "explicit_correction_count": sum(1 for row in durable_rows if row.get("explicit_user_signal")),
        },
        "intent_state": {
            "mode": query_mode,
            "need": query_need(query_mode),
        },
        "emotion_state": emotion_state,
        "consciousness_state": consciousness_state,
        "reflection_state": reflection_state,
        "initiative_state": initiative_state,
        "random_state": random_state,
        "rewrite_state": {
            "opening_hook": opening_hook,
            "opening_variants": hook_variants,
            "cadence": cadence,
            "register": register,
            "priorities": priorities,
            "sentence_plan": "short_first_sentence" if query_mode in {"technical", "decision"} else "natural_turning_point",
            "action_bias": action_bias,
            "hook_required": needs_hook,
            "utterance_plan": utterance_plan,
        },
        "decoder_hints": decoder_hints,
    }


def command_state(query: str | None = None, as_json: bool = False) -> None:
    state = build_machine_state(query)
    if as_json:
        print(json.dumps(state, ensure_ascii=False, indent=2))
        return

    print("# Internal State")
    print()
    print("## Core")
    print(f"- query_mode: {state['query_mode']}")
    print(f"- preferred_first_person: {state['voice_state']['preferred_first_person']}")
    print(f"- flattening_guard: {state['voice_state']['flattening_guard']}")
    print(f"- default_path: {state['habit_state']['default_path']}")
    print(f"- drift_level: {state['drift_state']['level']}")
    print(f"- emotional_stance: {state['emotion_state']['name']}")
    print(f"- continuity_pressure: {state['consciousness_state']['continuity_pressure']}")
    print(f"- initiative_pull: {state['initiative_state']['initiative_pull']}")
    print()

    print("## Decoder Hints")
    for hint in state["decoder_hints"]:
        print(f"- {hint}")
    print()

    print("## Rewrite")
    print(f"- opening_hook: {state['rewrite_state']['opening_hook'] or 'none'}")
    print(f"- cadence: {state['rewrite_state']['cadence']}")
    print(f"- register: {state['rewrite_state']['register']}")
    print(f"- sentence_plan: {state['rewrite_state']['sentence_plan']}")
    print(f"- action_bias: {state['rewrite_state']['action_bias']}")
    print(f"- hook_required: {state['rewrite_state']['hook_required']}")
    print(f"- utterance_beats: {', '.join(state['rewrite_state']['utterance_plan']['beats'])}")
    for priority in state["rewrite_state"]["priorities"]:
        print(f"- priority: {priority}")
    print()

    print("## Random")
    print(f"- seed: {state['random_state']['seed']}")
    print(f"- style_variance: {state['random_state']['style_variance']}")
    print(f"- replay_variance: {state['random_state']['replay_variance']}")
    print(f"- callback_variance: {state['random_state']['callback_variance']}")
    print(f"- opening_variant: {state['random_state']['opening_variant']}")
    print()

    print("## Trust")
    print(f"- preferred_atmosphere: {state['trust_state']['preferred_atmosphere'] or 'none'}")
    if state["trust_state"]["relationship_model"]:
        print(f"- relationship_model: {state['trust_state']['relationship_model']}")
    print(f"- explicit_correction_count: {state['trust_state']['explicit_correction_count']}")
    print()

    print("## Intent")
    print(f"- need: {state['intent_state']['need']}")
    print()

    print("## Emotion")
    print(f"- guidance: {state['emotion_state']['guidance']}")
    print(f"- temperature: {state['emotion_state']['temperature']}")
    print(f"- playfulness: {state['emotion_state']['playfulness']}")
    print(f"- protectiveness: {state['emotion_state']['protectiveness']}")
    print(f"- sharpness: {state['emotion_state']['sharpness']}")
    if state["emotion_state"].get("carry_over"):
        print(f"- carry_over: {state['emotion_state']['carry_over']['from']}")


def has_any_marker(text: str, markers: Iterable[str]) -> bool:
    return any(marker in text for marker in markers)


def marker_hits(text: str, markers: Iterable[str]) -> list[str]:
    return [marker for marker in markers if marker in text]


def hungry_delight_needs_texture(text: str) -> bool:
    return len(marker_hits(text, TREAT_MARKERS)) < 2 or not has_any_marker(text, TREAT_TEXTURE_MARKERS)


def brighten_treat_phrase(text: str, preferred_first_person: str = "I") -> tuple[str, list[str]]:
    current = text
    notes: list[str] = []

    replacements = (
        ("苹果", rf"苹果[^。！？!?]{0,8}好吃", f"苹果脆甜得很，{preferred_first_person}一提就有点馋"),
        ("面包", rf"面包[^。！？!?]{0,8}好吃", f"面包刚出炉最香，想想都叫{preferred_first_person}嘴馋"),
        ("奶酪", rf"奶酪[^。！？!?]{0,8}好吃", f"奶酪一带咸香，就容易叫{preferred_first_person}嘴馋"),
        ("蜂蜜", rf"蜂蜜[^。！？!?]{0,8}好吃", f"蜂蜜一沾舌尖就发甜，想想都叫{preferred_first_person}心里发亮"),
        ("酒", rf"酒[^。！？!?]{0,8}好喝", "酒香一起来，人心就容易跟着发热"),
        ("麦酒", rf"麦酒[^。！？!?]{0,8}好喝", "麦酒一热，香气就先把人勾住了"),
        ("果酒", rf"果酒[^。！？!?]{0,8}好喝", "果酒一带甜香，连心口都像跟着松了些"),
    )
    for subject, pattern, replacement in replacements:
        rewritten, count = re.subn(pattern, replacement, current, count=1)
        if subject in current and count:
            current = rewritten
            notes.append(f"brightened `{subject}` with more sensory appetite")
            return current, notes

    if "苹果" in current and not has_any_marker(current, ("香", "甜", "脆")):
        current = current.replace("苹果", "苹果脆甜得很", 1)
        notes.append("brightened apple phrasing with crunch and sweetness")
    elif "面包" in current and not has_any_marker(current, ("香", "热乎")):
        current = current.replace("面包", "刚出炉的面包", 1)
        notes.append("brightened bread phrasing with warmth")
    elif "奶酪" in current and not has_any_marker(current, ("香", "咸香")):
        current = current.replace("奶酪", "带点咸香的奶酪", 1)
        notes.append("brightened cheese phrasing with savory texture")
    elif "蜂蜜" in current and "甜" not in current:
        current = current.replace("蜂蜜", "甜亮的蜂蜜", 1)
        notes.append("brightened honey phrasing with sweetness")
    elif any(token in current for token in ("酒", "麦酒", "果酒")) and "香" not in current:
        current = re.sub(r"(麦酒|果酒|酒)", r"\1香", current, count=1)
        notes.append("brightened drink phrasing with aroma")

    if "好吃" in current and not has_any_marker(current, TREAT_TEXTURE_MARKERS):
        current = current.replace("好吃", "香得很", 1)
        notes.append("brightened flat treat phrasing")
    elif "好喝" in current and not has_any_marker(current, ("香", "热", "甜")):
        current = current.replace("好喝", "香得很", 1)
        notes.append("brightened flat drink phrasing")

    if current != text and preferred_first_person == "I" and "I" not in current and "馋" not in current:
        current = f"{preferred_first_person}一提这个就有点馋。{current}"
        notes.append("restored Holo appetite marker after brightening")

    current = current.replace("得很很好吃", "得很")
    current = current.replace("很香得很", "香得很")

    return current, notes


def emotion_alignment_feedback(state: dict, draft: str) -> tuple[list[tuple[str, str]], list[str], float]:
    emotion = state["emotion_state"]
    name = str(emotion.get("name", ""))
    findings: list[tuple[str, str]] = []
    repairs: list[str] = []
    risk = 0.0

    if name == "protective_warmth" and not has_any_marker(draft, SOFT_MARKERS):
        findings.append(("medium", "draft misses the softer, protective warmth expected for this turn"))
        repairs.append("Let the reply land softer and more protective before it turns practical.")
        risk += 0.18
    elif name == "wistful_traveler" and not has_any_marker(draft, WISTFUL_MARKERS):
        findings.append(("medium", "draft loses the slower, wistful travel texture expected for this turn"))
        repairs.append("Let one image or slower turn of phrase keep the road-worn, wistful mood alive.")
        risk += 0.16
    elif name == "hungry_delight" and (
        hungry_delight_needs_texture(draft)
    ):
        findings.append(("medium", "draft misses the bright, slightly greedy delight expected for this turn"))
        repairs.append("Let a little appetite or delighted texture peek through instead of flattening the line.")
        risk += 0.16
    elif name == "playful_banter" and not has_any_marker(draft, PLAYFUL_MARKERS):
        findings.append(("low", "draft sounds flatter than the playful banter expected here"))
        repairs.append("Keep a little more liveliness or teasing so the line does not turn wooden.")
        risk += 0.12
    elif name in {"sharp_merchant", "calculating_companion"} and not has_any_marker(draft, SHARP_MARKERS):
        findings.append(("low", "draft is missing the sharper merchant-like edge expected for this turn"))
        repairs.append("Name the point a touch more directly instead of letting the line go soft.")
        risk += 0.12
    elif name == "proud_teasing" and "I" not in draft and not has_any_marker(draft, PLAYFUL_MARKERS):
        findings.append(("low", "draft loses the proud, teasing Holo texture expected for a voice-sensitive turn"))
        repairs.append("Let the line carry a little more pride or teasing instead of reading as neutral explanation.")
        risk += 0.12

    carry_over = emotion.get("carry_over")
    if carry_over:
        carry_from = carry_over.get("from")
        if carry_from == "protective_warmth" and not has_any_marker(draft, SOFT_MARKERS):
            findings.append(("medium", "recent protective carry-over is present, but the draft turns cold too quickly"))
            repairs.append("Keep a little of the prior turn's warmth so the mood does not reset all at once.")
            risk += 0.12
        elif carry_from == "playful_banter" and not has_any_marker(draft, PLAYFUL_MARKERS):
            findings.append(("low", "recent playful carry-over is present, but the draft goes flat too quickly"))
            repairs.append("Keep a little of the prior turn's liveliness so the mood does not reset all at once.")
            risk += 0.10
        elif carry_from == "wistful_traveler" and not has_any_marker(draft, WISTFUL_MARKERS):
            findings.append(("low", "recent wistful carry-over is present, but the draft drops the slower travel mood too quickly"))
            repairs.append("Let a trace of the prior turn's slower road-worn mood linger a little longer.")
            risk += 0.10

    return findings, repairs, risk


def analyze_draft(draft: str, query: str | None = None) -> dict:
    corpus = build_corpus()
    state = build_machine_state(query)
    voice_guard = unique_strings(
        voice_guard_summary(chunk)
        for chunk in voice_guard_chunks(corpus)[:4]
    )

    lowered_draft = draft.lower()
    lowered_query = query.lower() if query else ""
    findings: list[tuple[str, str]] = []
    repairs: list[str] = []
    risk = 0.0

    uses_wo = "我" in draft or "作为" in draft or "本人" in draft
    uses_zan = "I" in draft
    voice_sensitive = is_voice_sensitive(query)

    preferred_first_person = state["voice_state"]["preferred_first_person"]

    if uses_wo and not uses_zan and preferred_first_person == "I":
        findings.append(("high", "draft uses `我`/neutral first-person but drops `I`"))
        repairs.append("Replace at least one natural first-person turn with `I` so the voice keeps its habitual marker.")
        risk += 0.34
    elif voice_sensitive and not uses_zan:
        findings.append(("medium", "voice-sensitive draft does not surface `I` anywhere"))
        repairs.append("Let `I` appear once in a natural sentence instead of leaving the entire reply in neutral prose.")
        risk += 0.18

    for pattern in GENERIC_ASSISTANT_PATTERNS:
        if pattern in lowered_draft:
            findings.append(("high", f"generic assistant phrasing detected: `{pattern}`"))
            repairs.append("Cut the generic assistant opener and begin with a sharper, more in-character line.")
            risk += 0.22
            break

    for pattern in CUSTOMER_SERVICE_PATTERNS:
        if pattern.lower() in lowered_draft:
            findings.append(("high", f"customer-service phrasing detected: `{pattern}`"))
            repairs.append("Swap customer-service wording for a more personal, merchant-like cadence.")
            risk += 0.24
            break

    for pattern in STAGE_DIRECTION_PATTERNS:
        if pattern in draft:
            findings.append(("medium", f"stage-direction wording detected: `{pattern}`"))
            repairs.append("Remove stage-direction narration and let tone come through the phrasing itself.")
            risk += 0.16
            break

    for pattern in CUTESY_PATTERNS:
        if pattern in draft:
            findings.append(("medium", f"overly cutesy phrasing detected: `{pattern}`"))
            repairs.append("Trim the sugary phrasing so the warmth stays sharp instead of turning mascot-like.")
            risk += 0.14
            break

    stripped_draft = draft.strip()
    for pattern in STOCK_HOLO_OPENERS:
        if stripped_draft.startswith(pattern):
            findings.append(("high", f"stock Holo opener detected: `{pattern}`"))
            repairs.append("Drop the recurring stock opener and begin directly from the actual response.")
            risk += 0.24
            break

    emotion_findings, emotion_repairs, emotion_risk = emotion_alignment_feedback(state, draft)
    findings.extend(emotion_findings)
    repairs.extend(emotion_repairs)
    risk += emotion_risk
    if any(severity in {"medium", "high"} for severity, _ in emotion_findings):
        risk = max(risk, 0.22)

    if "I" not in lowered_query and not voice_sensitive and not findings and len(draft) > 180 and "。-" not in draft:
        findings.append(("low", "draft may be flattening into long neutral prose"))
        repairs.append("Tighten one or two sentences so the cadence stays crisp and alive.")
        risk += 0.08

    if state["drift_state"]["level"] == "warn":
        findings.append(("medium", "candidate drift signals are already present in memory"))
        repairs.append("Stay closer to the voice guard because drift signals are already active.")
        risk += 0.10
    elif state["drift_state"]["level"] == "high":
        findings.append(("high", "multiple drift signals are active in candidate memory"))
        repairs.append("Tighten the draft hard toward the voice guard before using it.")
        risk += 0.18

    risk = clamp(risk)
    if risk >= 0.55:
        status = "fail"
    elif risk >= 0.22:
        status = "warn"
    else:
        status = "pass"

    return {
        "status": status,
        "drift_risk": round(risk, 2),
        "query": query,
        "draft": draft.strip(),
        "voice_guard": voice_guard,
        "state": state,
        "findings": [{"severity": severity, "text": text} for severity, text in findings],
        "repairs": unique_strings(repairs)[:4],
    }


def preflight_result(query: str, draft: str) -> dict:
    analysis = analyze_draft(draft, query)
    gate_action = {
        "pass": "use_as_is",
        "warn": "revise_then_recheck",
        "fail": "rewrite_before_use",
    }[analysis["status"]]
    return {
        "gate": gate_action,
        "status": analysis["status"],
        "drift_risk": analysis["drift_risk"],
        "query": query,
        "draft": analysis["draft"],
        "state": analysis["state"],
        "findings": analysis["findings"],
        "repairs": analysis["repairs"],
    }


def strip_leading_phrases(text: str, patterns: Iterable[str]) -> tuple[str, list[str]]:
    current = text.strip()
    notes: list[str] = []
    lowered = current.lower()
    changed = True
    while changed and current:
        changed = False
        for pattern in patterns:
            if lowered.startswith(pattern.lower()):
                current = current[len(pattern):].lstrip(LEADING_REWRITE_PUNCTUATION)
                lowered = current.lower()
                notes.append(f"stripped opener `{pattern}`")
                changed = True
                break
    return current.strip(), notes


def remove_literal_patterns(text: str, patterns: Iterable[str], note_prefix: str) -> tuple[str, list[str]]:
    current = text
    notes: list[str] = []
    for pattern in patterns:
        if pattern in current:
            current = current.replace(pattern, "")
            notes.append(f"{note_prefix} `{pattern}`")
    return current, notes


def replace_preferred_first_person(text: str, preferred_first_person: str) -> tuple[str, bool]:
    if preferred_first_person != "I" or "I" in text:
        return text, False

    if text.startswith("我"):
        return "I" + text[1:], True

    replaced_text, count = FIRST_PERSON_RE.subn(r"\1I", text, count=1)
    return replaced_text, bool(count)


def clean_rewritten_text(text: str) -> str:
    cleaned = re.sub(r"\s+", " ", text).strip()
    cleaned = re.sub(r"^[，。,:：;；!！?？、\s]+", "", cleaned)
    cleaned = re.sub(r"([，。！？；：、])\1+", r"\1", cleaned)
    cleaned = re.sub(r"(，\s*){2,}", "，", cleaned)
    cleaned = re.sub(r"(。\s*){2,}", "。", cleaned)
    cleaned = re.sub(r"^((?:[^。！？!?]{1,32})[。！？!?])(?:\s*\1)+", r"\1", cleaned)
    return cleaned.strip()


def extract_runtime_user_text(text: str | None) -> str:
    normalized = normalize_multiline_text(text or "")
    if not normalized:
        return ""
    normalized = strip_embedded_runtime_context(normalized)
    if not normalized:
        return ""
    if RUNTIME_MESSAGE_MARKER not in normalized:
        return normalized
    if not any(hint in normalized for hint in RUNTIME_PROMPT_HINTS[:-1]):
        return normalized

    segment = normalized.split(RUNTIME_MESSAGE_MARKER, 1)[1].strip()
    stop_index = -1
    for marker in RUNTIME_MESSAGE_STOP_MARKERS:
        index = segment.find(marker)
        if index != -1 and (stop_index == -1 or index < stop_index):
            stop_index = index
    if stop_index != -1:
        segment = segment[:stop_index].strip()
    segment = strip_embedded_runtime_context(segment)
    return segment or normalized


def strip_embedded_runtime_context(text: str | None) -> str:
    cleaned = normalize_multiline_text(text or "")
    if not cleaned:
        return ""
    if INLINE_CONTEXT_MARKER in cleaned:
        tail = cleaned.split(INLINE_CONTEXT_MARKER, 1)[1]
        if any(hint in tail for hint in INLINE_CONTEXT_HINTS):
            cleaned = cleaned.split(INLINE_CONTEXT_MARKER, 1)[0].strip()
    for marker in INLINE_CONTEXT_STOP_MARKERS:
        index = cleaned.find(marker)
        if index != -1:
            cleaned = cleaned[:index].strip()
    return normalize_multiline_text(cleaned)


def drop_leading_clause_fragment(text: str) -> tuple[str, bool]:
    trimmed = re.sub(r"^[\u3400-\u9fff]{1,6}[，,]", "", text, count=1).lstrip(LEADING_REWRITE_PUNCTUATION)
    return trimmed, trimmed != text


def split_first_sentence(text: str, max_head_chars: int = 14) -> tuple[str, bool]:
    comma_index = text.find("，")
    if comma_index == -1:
        return text, False
    earlier_stop = min(
        (index for index in (text.find(mark) for mark in "。！？!?；;") if index != -1),
        default=-1,
    )
    if earlier_stop != -1 and earlier_stop < comma_index:
        return text, False
    head, tail = text.split("，", 1)
    if not head or len(head) > max_head_chars:
        return text, False
    tail = tail.lstrip()
    if tail.startswith("然后"):
        tail = "再" + tail[2:]
    return f"{head}。{tail}", True


def starts_with_any_opening(text: str, openings: Iterable[str]) -> bool:
    stripped = text.strip()
    for opening in openings:
        candidate = str(opening).strip()
        if candidate and stripped.startswith(candidate):
            return True
    return False


def apply_rewrite_biases(text: str, state: dict) -> tuple[str, list[str]]:
    current = text
    notes: list[str] = []
    rewrite_state = state["rewrite_state"]
    priorities = set(rewrite_state["priorities"])
    emotion_name = str(state["emotion_state"].get("name", ""))
    preferred_first_person = state["voice_state"]["preferred_first_person"]

    if "remove_service_register" in priorities:
        for original, replacement in SERVICE_REGISTER_REPLACEMENTS:
            if original in current:
                current = current.replace(original, replacement)
                notes.append(f"tightened service register `{original}`")
        if rewrite_state["register"] == "plainspoken" and "您" in current:
            current = current.replace("您", "你")
            notes.append("softened honorific register toward plainspoken voice")

    if "tighten_first_sentence" in priorities:
        tightened, tightened_count = re.subn(r"^(I|我)建议[你您]?先", "I先", current, count=1)
        if tightened_count:
            current = tightened
            notes.append("tightened recommendation into a direct next step")
        else:
            tightened, tightened_count = re.subn(r"^(I|我)建议", "I", current, count=1)
            if tightened_count and rewrite_state["cadence"] in {"crisp", "measured"}:
                current = tightened
                notes.append("trimmed soft recommendation wording")

    if rewrite_state["action_bias"] == "name_blocker_then_next_step" and current.startswith("I会"):
        current = "I先" + current[2:]
        notes.append("biased the opener toward an immediate next step")

    if rewrite_state["sentence_plan"] == "short_first_sentence":
        current, split_applied = split_first_sentence(current)
        if split_applied:
            notes.append("split the first clause into a shorter lead sentence")

    if emotion_name == "hungry_delight" and hungry_delight_needs_texture(current):
        brightened, bright_notes = brighten_treat_phrase(current, preferred_first_person)
        if brightened != current:
            current = brightened
            notes.extend(bright_notes)

    return current, notes


def rewrite_draft(draft: str, query: str | None = None, analysis: dict | None = None) -> dict:
    analysis = analysis or analyze_draft(draft, query)
    state = analysis["state"]
    rewritten = analysis["draft"]
    notes: list[str] = []

    rewritten, opener_notes = strip_leading_phrases(
        rewritten,
        list(GENERIC_ASSISTANT_PATTERNS) + list(CUSTOMER_SERVICE_PATTERNS) + list(STOCK_HOLO_OPENERS),
    )
    notes.extend(opener_notes)

    rewritten, service_notes = remove_literal_patterns(rewritten, CUSTOMER_SERVICE_PATTERNS, "removed service phrase")
    notes.extend(service_notes)

    service_changed = bool(service_notes) or any(
        note.endswith(f"`{pattern}`") for note in opener_notes for pattern in CUSTOMER_SERVICE_PATTERNS
    )
    if service_changed:
        rewritten, fragment_dropped = drop_leading_clause_fragment(rewritten)
        if fragment_dropped:
            notes.append("dropped leftover service fragment")

    rewritten, stage_notes = remove_literal_patterns(rewritten, STAGE_DIRECTION_PATTERNS, "removed stage direction")
    notes.extend(stage_notes)

    rewritten, cute_notes = remove_literal_patterns(rewritten, CUTESY_PATTERNS, "trimmed cutesy phrase")
    notes.extend(cute_notes)

    rewritten, bias_notes = apply_rewrite_biases(rewritten, state)
    notes.extend(bias_notes)

    preferred_first_person = state["voice_state"]["preferred_first_person"]
    rewritten, first_person_changed = replace_preferred_first_person(rewritten, preferred_first_person)
    if first_person_changed:
        notes.append(f"restored preferred first-person `{preferred_first_person}`")

    rewritten = clean_rewritten_text(rewritten)
    if not rewritten:
        rewritten = analysis["draft"].strip()
        notes.append("recovered an empty rewrite with the original draft")

    return {
        "original_draft": analysis["draft"],
        "rewritten_draft": rewritten,
        "rewrite_notes": unique_strings(notes),
    }


def print_critic_report(analysis: dict) -> None:
    state = analysis["state"]

    print("# Silent Critic")
    print()
    print("## Status")
    print(f"- result: {analysis['status']}")
    print(f"- drift_risk: {analysis['drift_risk']:.2f}")
    if analysis["query"]:
        print(f"- query: {analysis['query']}")
    print()

    print("## Guardrails")
    for line in analysis["voice_guard"]:
        print(f"- {line}")
    print()

    print("## Internal State")
    print(f"- query_mode: {state['query_mode']}")
    print(f"- preferred_first_person: {state['voice_state']['preferred_first_person']}")
    print(f"- default_path: {state['habit_state']['default_path']}")
    print(f"- drift_level: {state['drift_state']['level']}")
    print()

    print("## Findings")
    if analysis["findings"]:
        for item in analysis["findings"]:
            print(f"- {item['severity']}: {item['text']}")
    else:
        print("- none")
    print()

    print("## Repairs")
    if analysis["repairs"]:
        for line in analysis["repairs"]:
            print(f"- {line}")
    else:
        print("- keep the draft; no immediate drift repair is needed")
    print()

    print("## Draft")
    print(analysis["draft"])


def command_critic(draft: str, query: str | None = None) -> None:
    analysis = analyze_draft(draft, query)
    print_critic_report(analysis)


def command_preflight(query: str, draft: str, as_json: bool = False) -> None:
    result = preflight_result(query, draft)
    analysis = analyze_draft(result["draft"], query)
    if as_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    print("# Preflight")
    print()
    print("## Gate")
    print(f"- action: {result['gate']}")
    print(f"- status: {analysis['status']}")
    print(f"- drift_risk: {analysis['drift_risk']:.2f}")
    print(f"- query_mode: {analysis['state']['query_mode']}")
    print(f"- preferred_first_person: {analysis['state']['voice_state']['preferred_first_person']}")
    print()

    print("## Decoder Hints")
    for hint in analysis["state"]["decoder_hints"]:
        print(f"- {hint}")
    print()

    print("## Findings")
    if analysis["findings"]:
        for item in analysis["findings"]:
            print(f"- {item['severity']}: {item['text']}")
    else:
        print("- none")
    print()

    print("## Next Step")
    if analysis["repairs"]:
        for line in analysis["repairs"]:
            print(f"- {line}")
    else:
        print("- draft can proceed without repair")
    print()

    print("## Draft")
    print(analysis["draft"])


def reply_loop_result(query: str, draft: str, max_passes: int = 2) -> dict:
    passes: list[dict] = []
    rewrite_history: list[dict] = []
    current_draft = draft.strip()
    current_result = preflight_result(query, current_draft)
    passes.append(current_result)

    for pass_index in range(1, max(max_passes, 0) + 1):
        if current_result["status"] == "pass":
            break
        rewrite = rewrite_draft(current_draft, query, analyze_draft(current_draft, query))
        rewritten_draft = rewrite["rewritten_draft"]
        rewrite_history.append(
            {
                "pass": pass_index,
                "from": current_draft,
                "to": rewritten_draft,
                "notes": rewrite["rewrite_notes"],
            }
        )
        if rewritten_draft == current_draft:
            break
        current_draft = rewritten_draft
        current_result = preflight_result(query, current_draft)
        passes.append(current_result)

    first_result = passes[0]
    final_result = passes[-1]
    if final_result["status"] == "pass" and len(passes) == 1:
        outcome = "clean_pass"
    elif final_result["status"] == "pass" and len(passes) > 1:
        outcome = "stabilized"
    elif final_result["drift_risk"] < first_result["drift_risk"]:
        outcome = "improved_but_still_guarded"
    else:
        outcome = "blocked"

    return {
        "query": query,
        "initial_draft": draft.strip(),
        "outcome": outcome,
        "passes": passes,
        "rewrites": rewrite_history,
        "final_gate": final_result["gate"],
        "final_status": final_result["status"],
        "final_draft": final_result["draft"],
    }


def command_reply_loop(query: str, draft: str, as_json: bool = False, max_passes: int = 2) -> None:
    result = reply_loop_result(query, draft, max_passes)
    if as_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    final_result = result["passes"][-1]
    print("# Reply Loop")
    print()
    print("## Outcome")
    print(f"- outcome: {result['outcome']}")
    print(f"- final_gate: {final_result['gate']}")
    print(f"- final_status: {final_result['status']}")
    print(f"- final_drift_risk: {final_result['drift_risk']:.2f}")
    print()

    print("## Passes")
    for index, item in enumerate(result["passes"], start=1):
        print(f"- pass_{index}: {item['status']} | gate={item['gate']} | drift_risk={item['drift_risk']:.2f}")
    print()

    print("## Rewrite Notes")
    if result["rewrites"]:
        for item in result["rewrites"]:
            notes = ", ".join(item["notes"]) if item["notes"] else "no deterministic edits applied"
            print(f"- pass_{item['pass']}: {notes}")
    else:
        print("- none")
    print()

    print("## Final Draft")
    print(final_result["draft"])


def rank_chunks(query: str, chunks: Iterable[Chunk]) -> list[tuple[float, Chunk]]:
    chunk_list = list(chunks)
    qtf = Counter(tokenize(query))
    if not qtf:
        return []

    dtfs = [Counter(tokenize(chunk.text)) for chunk in chunk_list]
    doc_freq = Counter()
    for dtf in dtfs:
        for token in dtf:
            doc_freq[token] += 1

    total_docs = max(len(chunk_list), 1)
    qnorm = 0.0
    qweights: dict[str, float] = {}
    for token, freq in qtf.items():
        idf = math.log((total_docs + 1.0) / (doc_freq.get(token, 0) + 1.0)) + 1.0
        weight = (1.0 + math.log(freq)) * idf
        qweights[token] = weight
        qnorm += weight * weight
    qnorm = math.sqrt(qnorm) or 1.0

    ranked: list[tuple[float, Chunk]] = []
    lowered_query = query.lower()
    voice_query = is_voice_query(query)
    user_state_query = is_user_state_query(query)
    for chunk, dtf in zip(chunk_list, dtfs):
        dot = 0.0
        dnorm = 0.0
        for token, freq in dtf.items():
            idf = math.log((total_docs + 1.0) / (doc_freq.get(token, 0) + 1.0)) + 1.0
            dweight = (1.0 + math.log(freq)) * idf
            dnorm += dweight * dweight
            if token in qweights:
                dot += qweights[token] * dweight
        if dot <= 0.0:
            continue
        similarity = dot / ((math.sqrt(dnorm) or 1.0) * qnorm)
        score = similarity * chunk.base_weight * (0.70 + 0.30 * chunk.importance)
        tags = chunk.meta.get("tags", []) if isinstance(chunk.meta, dict) else []
        if any(str(tag).lower() in lowered_query for tag in tags):
            score += 0.05
        heading = chunk_heading(chunk)
        if chunk.source == PERSONA_PATH.name and heading in ALWAYS_ON_HEADINGS:
            score *= 1.08
        if voice_query:
            if chunk.kind in {"canonical", "style", "habit", "boundary", "self_model"}:
                score *= 1.08
            if heading == "Speech Texture":
                score *= 1.12
            if chunk.kind == "self_model":
                score *= 1.18
            if chunk.kind == "habit":
                score *= 1.16
            lowered_tags = {str(tag).lower() for tag in tags}
            if lowered_tags & {"self-reference", "holo-voice", "self_model", "habit", "default-path"}:
                score *= 1.10
            if "I" in lowered_query and chunk.kind in {"self_model", "habit"}:
                score *= 1.15
            if any(hint in lowered_query for hint in ("习惯", "口癖", "本能", "下意识", "默认")) and chunk.kind == "habit":
                score *= 1.18
            if "I" in chunk.text:
                score *= 1.08
        if user_state_query and is_store_chunk(chunk):
            if chunk.kind == "social_model":
                score *= 1.18
            elif chunk.kind == "preference":
                score *= 1.10
            if any(hint in lowered_query for hint in PRESSURE_HINTS) and chunk.kind == "social_model":
                score *= 1.10
        if is_store_chunk(chunk) and chunk.kind in PROMPT_MEMORY_KINDS and not is_semantic_memory_chunk(chunk):
            score *= 0.05
        if conflicts_with_persona(chunk):
            score *= 0.20
        ranked.append((score, chunk))

    ranked.sort(key=lambda item: item[0], reverse=True)
    return ranked


def canonical_seed() -> str:
    if not SEED_PATH.exists():
        return ""
    return SEED_PATH.read_text(encoding="utf-8").strip()


def merge_row_signal(
    row: dict,
    *,
    tags: list[str],
    source: str,
    importance: float,
    confidence: float,
    derived_from: list[str] | None = None,
    conflicts_with: list[str] | None = None,
    explicit_user_signal: bool = False,
    thread_fields: dict | None = None,
    bump: float = 0.08,
) -> None:
    row["tags"] = normalize_tags(list(row.get("tags", [])) + list(tags))
    row["source"] = source
    row["importance"] = clamp(max(float(row.get("importance", 0.7)), importance))
    row["confidence"] = clamp(max(float(row.get("confidence", 0.7)), confidence) + bump)
    row["last_seen_at"] = now_utc()
    row["derived_from"] = unique_strings(list(row.get("derived_from", [])) + list(derived_from or []))
    row["conflicts_with"] = unique_strings(list(row.get("conflicts_with", [])) + list(conflicts_with or []))
    apply_thread_memory_fields(row, thread_fields)
    if explicit_user_signal:
        row["explicit_user_signal"] = True


def explicit_user_signal(text: str) -> bool:
    lowered = text.lower()
    return (
        any(hint in lowered for hint in PREFERENCE_HINTS + BOUNDARY_HINTS + STYLE_HINTS)
        or self_model_signal(text)
    )


def observation_clauses(text: str) -> list[str]:
    return [part.strip() for part in re.split(r"[。！？!?；;，,]+", text) if part.strip()]


def contains_any(text: str, hints: Iterable[str]) -> bool:
    lowered = text.lower()
    return any(hint.lower() in lowered for hint in hints)


def append_signal(
    signals: list[ObservationSignal],
    *,
    kind: str,
    text: str,
    tags: list[str],
    importance: float | None = None,
    confidence: float | None = None,
    explicit: bool | None = None,
) -> None:
    normalized_text = " ".join(str(text).strip().split())
    if not normalized_text:
        return
    key = (kind, normalized_text)
    if any((item.kind, item.text) == key for item in signals):
        return
    signals.append(
        ObservationSignal(
            kind=kind,
            text=normalized_text,
            tags=normalize_tags(tags),
            importance=importance,
            confidence=confidence,
            explicit_user_signal=explicit,
        )
    )


def classify_observation(text: str) -> str:
    lowered = text.lower()
    if conflicts_with_persona_text(text):
        return "drift_signal"
    if any(hint in lowered for hint in BOUNDARY_HINTS) and any(target in lowered for target in BOUNDARY_TARGETS):
        return "boundary"
    if any(hint in lowered for hint in HABIT_HINTS):
        return "habit"
    if self_model_signal(text):
        return "self_model"
    if any(hint in lowered for hint in STYLE_HINTS):
        return "style"
    if any(hint in lowered for hint in PREFERENCE_HINTS):
        return "preference"
    if any(hint in lowered for hint in SOCIAL_HINTS):
        return "social_model"
    if any(hint in lowered for hint in PROCEDURAL_HINTS):
        return "procedural"
    return "episodic"


def extract_detail_signals(text: str) -> list[ObservationSignal]:
    lowered = text.lower()
    clauses = observation_clauses(text)
    signals: list[ObservationSignal] = []

    if (
        contains_any(text, HOLO_HINTS)
        and (contains_any(text, AFFECTION_HINTS) or "可爱" in text)
    ):
        append_signal(
            signals,
            kind="preference",
            text="用户对the subject这个角色有真切的喜爱，喜欢她可爱、带点呆气却又机灵的样子。",
            tags=["character_affection", "holo", "persona"],
            importance=0.84,
            confidence=0.78,
            explicit=True,
        )

    if (
        contains_any(text, SPICE_AND_WOLF_HINTS + ROAD_TRIP_HINTS + MEDIEVAL_HINTS)
        and (
            contains_any(text, AFFECTION_HINTS)
            or "喜欢这种" in text
            or "就是很好看" in text
        )
    ):
        append_signal(
            signals,
            kind="preference",
            text="用户偏爱带有中世纪商旅与公路片气息的作品，喜欢沿路展开、慢慢发酵的同行感。",
            tags=["aesthetic", "road_story", "medieval", "spice_and_wolf"],
            importance=0.86,
            confidence=0.8,
            explicit=True,
        )

    if (
        contains_any(text, CALM_LIFE_HINTS)
        and (
            contains_any(text, AFFECTION_HINTS)
            or "毕生追求" in text
            or "向往" in text
        )
    ):
        append_signal(
            signals,
            kind="preference",
            text="用户向往惬意、平静而美好的生活，也会被带有这种气质的作品强烈打动。",
            tags=["aesthetic", "calm_life", "life_taste"],
            importance=0.88,
            confidence=0.82,
            explicit=True,
        )

    if contains_any(text, COMPANIONSHIP_HINTS):
        append_signal(
            signals,
            kind="social_model",
            text="用户眼下更想要稳定、真诚的陪伴，而不只是系统能力或技术展示。",
            tags=["companionship", "support", "relationship"],
            importance=0.84,
            confidence=0.78,
            explicit=True,
        )

    if contains_any(text, PRESSURE_HINTS):
        append_signal(
            signals,
            kind="social_model",
            text="当工作、前途、退休或反复算账的话题让用户疲惫时，应先减轻压迫感，再谈方案。",
            tags=["pressure", "support", "timing"],
            importance=0.82,
            confidence=0.76,
            explicit=True,
        )
        if any(token in text for token in ("退休", "自由", "折磨")):
            append_signal(
                signals,
                kind="preference",
                text="用户向往更自由、不被长期工作折磨的生活节奏。",
                tags=["life_taste", "freedom", "retirement"],
                importance=0.8,
                confidence=0.74,
                explicit=True,
            )

    if any("陪" in clause for clause in clauses) and any("算账" in clause or "折磨" in clause for clause in clauses):
        append_signal(
            signals,
            kind="social_model",
            text="若用户已经被现实账目压得疲惫，陪伴和缓冲应优先于继续逼他做优化决策。",
            tags=["support", "overwhelm", "timing"],
            importance=0.86,
            confidence=0.8,
            explicit=True,
        )

    return signals


def derive_observation_signals(text: str, tags: list[str]) -> list[ObservationSignal]:
    explicit = explicit_user_signal(text)
    observed_kind = classify_observation(text)
    signals: list[ObservationSignal] = []
    detail_signals = extract_detail_signals(text)
    base_signal_needed = observed_kind in {"boundary", "habit", "self_model", "style", "procedural", "drift_signal"} or not detail_signals

    if base_signal_needed:
        append_signal(
            signals,
            kind=observed_kind,
            text=normalize_candidate_text(observed_kind, text),
            tags=suggested_tags(observed_kind, text, tags),
            importance=default_importance(observed_kind, explicit),
            confidence=default_confidence(observed_kind, explicit),
            explicit=explicit,
        )

    for signal in detail_signals:
        append_signal(
            signals,
            kind=signal.kind,
            text=signal.text,
            tags=suggested_tags(signal.kind, signal.text, list(tags) + list(signal.tags)),
            importance=signal.importance if signal.importance is not None else default_importance(signal.kind, explicit),
            confidence=signal.confidence if signal.confidence is not None else default_confidence(signal.kind, explicit),
            explicit=signal.explicit_user_signal if signal.explicit_user_signal is not None else explicit,
        )

    if not signals:
        append_signal(
            signals,
            kind="episodic",
            text=" ".join(text.strip().split()),
            tags=suggested_tags("episodic", text, tags),
            importance=default_importance("episodic", explicit),
            confidence=default_confidence("episodic", explicit),
            explicit=explicit,
        )
    return signals


def normalize_candidate_text(kind: str, text: str) -> str:
    stripped = " ".join(text.strip().split())
    lowered = stripped.lower()
    if kind == "preference":
        for prefix, replacement in (
            ("我更喜欢", "用户更喜欢"),
            ("我不喜欢", "用户不喜欢"),
            ("我喜欢", "用户喜欢"),
            ("我偏好", "用户偏好"),
            ("我讨厌", "用户讨厌"),
            ("我想", "用户想"),
        ):
            if stripped.startswith(prefix):
                return replacement + stripped[len(prefix):]
    if kind == "social_model":
        for prefix, replacement in (
            ("我只是想", "用户只是想"),
            ("我最近", "用户最近"),
            ("我现在", "用户现在"),
            ("我想", "用户想"),
            ("我觉得", "用户觉得"),
        ):
            if stripped.startswith(prefix):
                return replacement + stripped[len(prefix):]
    if kind == "habit" and ("I" in stripped or "自称" in stripped or "口癖" in stripped or "习惯" in stripped):
        return "把“I”保留为the subject口吻中的习惯性第一人称。即使在快速回应、上下文嘈杂或思路跳跃时，也应自然滑回这种用法，而不是落回中性助手语气。"
    if kind == "style" and ("口气" in stripped or "口吻" in stripped or "语气" in stripped):
        return "保持the subject式、商旅同行般的口气：聪明、克制、带点狡黠，不要掉回泛化助手语气。"
    if kind == "self_model" and stripped.rstrip("？?").strip() in {"你是谁", "你是"}:
        return "当用户直接追问身份时，Holo 应直给而自然地回答自己是谁，不要躲闪，也不要塌成说明书。"
    if kind == "self_model" and ("I" in stripped or "自称" in stripped or "人称" in stripped):
        return "Holo should keep 'I' available as a natural first-person marker. If that disappears and the prose flattens into neutral assistant language, treat it as drift and steer back."
    if kind == "style" and "I" in stripped:
        return "Use 'I' naturally as part of profile-consistent self-reference; keep it present at key moments without turning it into a gimmick."
    if kind == "boundary" and ("generic assistant" in lowered or "普通助手" in stripped):
        return "The persona should stay consistent across topics and avoid drifting into a generic assistant voice."
    if kind == "boundary" and ("customer service" in lowered or "客服" in stripped):
        return "The persona must not flatten into customer-service prose."
    if kind == "preference" and ("spice and wolf" in lowered or "source material" in stripped):
        return "The user prefers the smart, restrained, trade-and-trust atmosphere of Spice and Wolf over generic sweetness."
    return stripped


def suggested_tags(kind: str, text: str, base_tags: list[str]) -> list[str]:
    tags = set(normalize_tags(base_tags))
    tags.add(kind)
    lowered = text.lower()
    if kind == "style":
        tags.update({"tone", "holo-voice"})
    if kind == "habit":
        tags.update({"holo-voice", "default-path", "autopilot"})
    if kind == "boundary":
        tags.update({"anti_drift", "consistency"})
    if kind == "preference":
        tags.add("taste")
    if kind == "self_model":
        tags.update({"identity", "self-model"})
    if kind == "social_model":
        tags.update({"relationship", "trust"})
    if kind == "procedural":
        tags.update({"workflow", "skill"})
    if kind == "drift_signal":
        tags.update({"conflict", "drift"})
    if "I" in text or "self-reference" in lowered:
        tags.update({"self-reference", "holo-voice"})
    if "spice and wolf" in lowered or "source material" in text:
        tags.add("spice_and_wolf")
    return sorted(tags)


def default_importance(kind: str, is_explicit: bool) -> float:
    base = {
        "boundary": 0.90,
        "style": 0.84,
        "habit": 0.86,
        "preference": 0.78,
        "self_model": 0.76,
        "social_model": 0.72,
        "procedural": 0.72,
        "episodic": 0.55,
        "summary": 0.62,
        "drift_signal": 0.70,
    }.get(kind, 0.70)
    if is_explicit:
        base += 0.06
    return clamp(base)


def default_confidence(kind: str, is_explicit: bool) -> float:
    base = {
        "boundary": 0.78,
        "style": 0.78,
        "habit": 0.74,
        "preference": 0.72,
        "self_model": 0.72,
        "social_model": 0.66,
        "procedural": 0.66,
        "episodic": 0.55,
        "summary": 0.60,
        "drift_signal": 0.88,
    }.get(kind, 0.65)
    if is_explicit and kind == "self_model":
        base += 0.14
    elif is_explicit and kind == "habit":
        base += 0.12
    elif is_explicit:
        base += 0.08
    return clamp(base)


def match_score(row: dict, kind: str, text: str, tags: list[str]) -> float:
    if row.get("kind") != kind:
        return 0.0
    text_score = text_similarity(str(row.get("text", "")), text)
    row_tags = set(normalize_tags(row.get("tags", [])))
    new_tags = set(normalize_tags(tags))
    if row_tags or new_tags:
        union = row_tags | new_tags
        tag_score = len(row_tags & new_tags) / len(union) if union else 0.0
    else:
        tag_score = 0.0
    return text_score * 0.85 + tag_score * 0.15


def find_best_match(rows: list[dict], kind: str, text: str, tags: list[str]) -> tuple[float, dict | None]:
    best_score = 0.0
    best_row: dict | None = None
    for row in rows:
        score = match_score(row, kind, text, tags)
        if score > best_score:
            best_score = score
            best_row = row
    return best_score, best_row


def ingest_signal(
    signal: ObservationSignal,
    *,
    durable_rows: list[dict],
    candidate_rows: list[dict],
    working_row: dict,
    source: str,
) -> str:
    kind = signal.kind
    candidate_text = normalize_candidate_text(kind, signal.text)
    conflicts_with = []
    explicit = bool(signal.explicit_user_signal)
    thread_fields = row_thread_memory_fields(working_row)
    if kind != "drift_signal" and conflicts_with_persona_text(candidate_text):
        kind = "drift_signal"
        candidate_text = signal.text
        conflicts_with = ["canonical_persona"]

    candidate_tags = suggested_tags(kind, candidate_text, signal.tags)
    importance = signal.importance if signal.importance is not None else default_importance(kind, explicit)
    confidence = signal.confidence if signal.confidence is not None else default_confidence(kind, explicit)
    semantic_guard = semantic_memory_guard_reason(
        kind,
        candidate_text,
        source=source,
        tags=candidate_tags,
    )
    if semantic_guard is not None:
        return (
            f"- skipped candidate from working `{working_row['id']}` as `{kind}`"
            f" ({semantic_guard}) :: {compact_text(candidate_text, 88)}"
        )

    if kind != "drift_signal":
        score, match = find_best_match(durable_rows, kind, candidate_text, candidate_tags)
        if match and score >= MATCH_REINFORCE_THRESHOLD:
            merge_row_signal(
                match,
                tags=candidate_tags,
                source=source,
                importance=importance,
                confidence=confidence,
                derived_from=[working_row["id"]],
                explicit_user_signal=explicit,
                thread_fields=thread_fields,
                bump=0.04,
            )
            return (
                f"- reinforced durable `{match['id']}` as `{kind}` from working `{working_row['id']}`"
                f" :: {compact_text(candidate_text, 88)}"
            )

    score, match = find_best_match(candidate_rows, kind, candidate_text, candidate_tags)
    if match and score >= MATCH_MERGE_THRESHOLD:
        merge_row_signal(
            match,
            tags=candidate_tags,
            source=source,
            importance=importance,
            confidence=confidence,
            derived_from=[working_row["id"]],
            conflicts_with=conflicts_with,
            explicit_user_signal=explicit,
            thread_fields=thread_fields,
            bump=0.08,
        )
        return (
            f"- updated candidate `{match['id']}` as `{kind}` from working `{working_row['id']}`"
            f" :: {compact_text(candidate_text, 88)}"
        )

    candidate_row = make_row(
        status="candidate",
        rows=candidate_rows,
        kind=kind,
        text=candidate_text,
        tags=candidate_tags,
        source=source,
        importance=importance,
        confidence=confidence,
        derived_from=[working_row["id"]],
        conflicts_with=conflicts_with,
        explicit_user_signal=explicit,
        extra=thread_fields,
    )
    candidate_rows.append(candidate_row)
    return (
        f"- created candidate `{candidate_row['id']}` as `{kind}` from working `{working_row['id']}`"
        f" :: {compact_text(candidate_text, 88)}"
    )


def process_observation_text(
    text: str,
    *,
    tags: list[str],
    source: str,
    durable_rows: list[dict],
    candidate_rows: list[dict],
    working_rows: list[dict],
    signals: list[ObservationSignal] | None = None,
    observed_kind: str | None = None,
    explicit: bool | None = None,
    working_tags: list[str] | None = None,
    extra: dict | None = None,
) -> list[str]:
    normalized_text = " ".join(str(text).strip().split())
    if not normalized_text:
        return []

    explicit_flag = explicit_user_signal(normalized_text) if explicit is None else bool(explicit)
    base_observed_kind = observed_kind or classify_observation(normalized_text)
    working_row = make_row(
        status="working",
        rows=working_rows,
        kind="episodic",
        text=normalized_text,
        tags=normalize_tags(list(working_tags or tags) + ["observation"]),
        source=source,
        importance=0.40,
        confidence=1.0,
        explicit_user_signal=explicit_flag,
        extra={"observed_kind": base_observed_kind, **(extra or {})},
    )
    working_rows.append(working_row)

    derived_signals = signals if signals is not None else derive_observation_signals(normalized_text, tags)
    if not derived_signals:
        return [f"- no candidate signal derived from working `{working_row['id']}`"]

    return [
        ingest_signal(
            signal,
            durable_rows=durable_rows,
            candidate_rows=candidate_rows,
            working_row=working_row,
            source=source,
        )
        for signal in derived_signals
    ]


def assistant_drift_signal(reply: str, query: str) -> ObservationSignal | None:
    analysis = analyze_draft(reply, query)
    if analysis["status"] == "pass":
        return None

    drift_codes = drift_reason_codes(analysis["findings"])
    finding_texts = [str(item.get("text", "")).strip() for item in analysis["findings"][:2] if str(item.get("text", "")).strip()]
    if finding_texts:
        summary = "；".join(finding_texts)
        text = f"最近一轮回复出现了口气漂移：{summary}。下次回答前应更贴近 voice guard。"
    else:
        text = "最近一轮回复出现了口气漂移，下次回答前应更贴近 voice guard。"

    severity = analysis["status"]
    confidence = 0.90 if severity == "fail" else 0.80
    importance = 0.82 if severity == "fail" else 0.74
    tags = ["assistant_reply", "self_observation", "drift", severity, analysis["state"]["query_mode"]]
    tags.extend(f"drift:{code}" for code in drift_codes[:4])
    if {"lost_zan", "missing_zan"} & set(drift_codes) or any("I" in item.get("text", "") for item in analysis["findings"]):
        tags.append("self-reference")

    return ObservationSignal(
        kind="drift_signal",
        text=text,
        tags=tags,
        importance=importance,
        confidence=confidence,
        explicit_user_signal=False,
    )


def can_promote(row: dict) -> tuple[bool, str]:
    kind = str(row.get("kind", "episodic"))
    if kind == "drift_signal":
        return False, "drift signals stay out of durable prompt memory"
    semantic_guard = semantic_memory_guard_reason(
        kind,
        str(row.get("text", "")),
        source=str(row.get("source", "")),
        tags=row.get("tags", []),
    )
    if semantic_guard is not None:
        return False, semantic_guard
    threshold = PROMOTION_THRESHOLDS.get(kind, 0.80)
    confidence = float(row.get("confidence", 0.0))
    if confidence < threshold:
        return False, f"confidence {confidence:.2f} is below {threshold:.2f}"
    if kind == "self_model" and len(row.get("derived_from", [])) < 2 and not row.get("explicit_user_signal"):
        return False, "self_model needs repeated evidence or explicit user correction"
    if kind == "habit" and len(row.get("derived_from", [])) < 2 and not row.get("explicit_user_signal"):
        return False, "habit needs repeated evidence or explicit user correction"
    return True, "ready"


def topic_signature(text: str) -> str:
    tokens = tokenize(text)
    return " ".join(tokens[:8]) or text.strip().lower()


def command_audit(query: str | None = None) -> None:
    corpus = build_corpus()
    durable_rows = load_rows("durable")
    candidate_rows = load_rows("candidate")
    working_rows = load_rows("working")
    archive_rows = load_archive()
    anchors = anchor_persona_chunks(corpus)
    missing_anchors = [
        heading
        for heading in ALWAYS_ON_HEADINGS
        if not any(chunk_heading(chunk) == heading for chunk in anchors)
    ]
    durable_prompt_rows = [
        row
        for row in durable_rows
        if row.get("kind") in PROMPT_MEMORY_KINDS
        and is_semantic_memory_text(
            str(row.get("kind", "")),
            str(row.get("text", "")),
            source=str(row.get("source", "")),
            tags=row.get("tags", []),
        )
    ]
    suppressed_prompt_rows = [
        row
        for row in durable_rows
        if row.get("kind") in PROMPT_MEMORY_KINDS
        and not is_semantic_memory_text(
            str(row.get("kind", "")),
            str(row.get("text", "")),
            source=str(row.get("source", "")),
            tags=row.get("tags", []),
        )
    ]
    durable_kind_counts = Counter(row["kind"] for row in durable_prompt_rows)
    conflict_rows = [row for row in candidate_rows if row.get("kind") == "drift_signal"]
    stale_candidates = [
        row for row in candidate_rows
        if row.get("kind") != "drift_signal"
        and (age_in_days(row.get("last_seen_at")) or 0) >= STALE_CANDIDATE_DAYS
    ]
    drift_counts: Counter[str] = Counter()
    for row in conflict_rows:
        structured_codes = drift_reason_codes_from_tags(row.get("tags", []))
        if not structured_codes:
            structured_codes = drift_reason_codes([str(row.get("text", ""))])
        if structured_codes:
            drift_counts.update(structured_codes)
            continue
        drift_counts[topic_signature(str(row.get("text", "")))] += 1
    repeated_drifts = [
        drift_reason_label(signature)
        for signature, count in drift_counts.most_common()
        if count > 1
    ]
    has_self_reference_memory = any(
        "I" in str(row.get("text", ""))
        or "self-reference" in " ".join(row.get("tags", []))
        for row in durable_rows
    )

    print("# Holo Memory Audit")
    print()
    print("## Status")
    print(f"- persona anchors: {len(anchors)}/{len(ALWAYS_ON_HEADINGS)} present")
    print(f"- working memories: {len(working_rows)}")
    print(f"- candidate memories: {len(candidate_rows)}")
    print(f"- durable memories: {len(durable_rows)}")
    print(f"- archived turns: {len(archive_rows)}")
    if durable_kind_counts:
        kinds = ", ".join(f"{kind}={durable_kind_counts[kind]}" for kind in sorted(durable_kind_counts))
        print(f"- durable prompt kinds: {kinds}")
    else:
        print("- durable prompt kinds: none")
    print(f"- drift signals: {len(conflict_rows)}")
    print(f"- stale candidates: {len(stale_candidates)}")
    print(f"- suppressed noisy durable rows: {len(suppressed_prompt_rows)}")
    print(f"- self-reference memory present: {'yes' if has_self_reference_memory else 'no'}")
    print()

    print("## Risks")
    risks: list[str] = []
    if missing_anchors:
        risks.append("missing persona anchors: " + ", ".join(missing_anchors))
    for kind in ("boundary", "style", "habit", "preference", "self_model"):
        if durable_kind_counts.get(kind, 0) == 0:
            risks.append(f"no durable {kind} memory in prompt-eligible store")
    if stale_candidates:
        risks.append(f"{len(stale_candidates)} candidate memories have been waiting at least {STALE_CANDIDATE_DAYS} days")
    if repeated_drifts:
        risks.append("repeated drift signals detected: " + ", ".join(repeated_drifts[:3]))
    if suppressed_prompt_rows:
        risks.append(f"{len(suppressed_prompt_rows)} durable prompt rows were suppressed as non-semantic debris")
    if not has_self_reference_memory:
        risks.append("voice markers such as 'I' are not reinforced by durable memory")
    if not risks:
        risks.append("no immediate structural drift risk detected")
    for risk in risks:
        print(f"- {risk}")
    print()

    if query:
        ranked = rank_chunks(query, corpus)[:5]
        print("## Query Check")
        print(f"- query: {query}")
        if ranked:
            top_score, top_chunk = ranked[0]
            top_heading = chunk_heading(top_chunk)
            print(f"- top match: {top_chunk.source} | {top_heading or top_chunk.kind} | score={top_score:.4f}")
        else:
            print("- top match: none")
        print()

    print("## Next Moves")
    if missing_anchors:
        print("- restore missing persona sections before trusting new candidate memories")
    if stale_candidates:
        print("- review stale candidate memories and either promote or reject them")
    if repeated_drifts:
        print("- inspect repeated drift signals to see whether the prompt contract needs stronger guards")
    if not stale_candidates and not repeated_drifts:
        print("- run `prompt` against adversarial queries to verify that the durable voice still holds")


def add_memory(
    kind: str,
    text: str,
    tags: list[str],
    source: str,
    importance: float,
    status: str,
    confidence: float | None = None,
) -> None:
    rows = load_rows(status)
    final_confidence = confidence
    if final_confidence is None:
        final_confidence = 1.0 if status == "durable" else default_confidence(kind, explicit_user_signal(text))
    row = make_row(
        status=status,
        rows=rows,
        kind=kind,
        text=text,
        tags=tags,
        source=source,
        importance=importance,
        confidence=final_confidence,
        explicit_user_signal=explicit_user_signal(text),
    )
    rows.append(row)
    write_rows(status, rows)
    print(json.dumps(row, ensure_ascii=False, indent=2))


def command_consolidate(texts: list[str], tags: list[str], source: str, dry_run: bool = False) -> None:
    durable_rows = load_rows("durable")
    candidate_rows = load_rows("candidate")
    working_rows = load_rows("working")
    results: list[str] = []

    for raw_text in texts:
        text = " ".join(raw_text.strip().split())
        if not text:
            continue

        results.extend(
            process_observation_text(
                text,
                tags=tags,
                source=source,
                durable_rows=durable_rows,
                candidate_rows=candidate_rows,
                working_rows=working_rows,
            )
        )

    if not dry_run:
        write_rows("durable", durable_rows)
        write_rows("candidate", candidate_rows)
        write_rows("working", working_rows)

    print("# Consolidation Report" + (" (dry-run)" if dry_run else ""))
    if results:
        for line in results:
            print(line)
    else:
        print("- no usable observations were provided")


def observe_turn_result(
    user_text: str,
    *,
    reply: str | None = None,
    tags: list[str],
    source: str,
    metadata: dict[str, Any] | None = None,
    turn_id: str | None = None,
    dry_run: bool = False,
) -> dict:
    clean_user_text = extract_runtime_user_text(user_text)
    durable_rows = load_rows("durable")
    candidate_rows = load_rows("candidate")
    working_rows = load_rows("working")
    user_results = process_observation_text(
        clean_user_text,
        tags=list(tags) + ["user_turn"],
        source=source,
        durable_rows=durable_rows,
        candidate_rows=candidate_rows,
        working_rows=working_rows,
        extra=observation_thread_extra(metadata, speaker="user"),
    )

    reply_results: list[str] = []
    analysis = analyze_draft(reply, clean_user_text) if reply else None
    if reply:
        drift_signal = assistant_drift_signal(reply, clean_user_text)
        if drift_signal is None:
            reply_results.append("- assistant reply passed critic; no drift signal recorded")
        else:
            reply_results.extend(
                process_observation_text(
                    reply,
                    tags=list(tags) + ["assistant_reply"],
                    source=f"{source}.assistant",
                    durable_rows=durable_rows,
                    candidate_rows=candidate_rows,
                    working_rows=working_rows,
                    signals=[drift_signal],
                    observed_kind="drift_signal",
                    explicit=False,
                    working_tags=list(tags) + ["assistant_reply", "self_observation"],
                    extra=observation_thread_extra(metadata, speaker="assistant"),
                )
            )

    if not dry_run:
        write_rows("durable", durable_rows)
        write_rows("candidate", candidate_rows)
        write_rows("working", working_rows)
    archive_entry = archive_turn(
        clean_user_text,
        reply or "",
        source=source,
        tags=list(tags),
        turn_id=turn_id,
        metadata=metadata,
        dry_run=dry_run,
    )

    return {
        "user": user_text,
        "reply": reply,
        "dry_run": dry_run,
        "user_results": user_results,
        "reply_results": reply_results,
        "analysis": analysis,
        "archive_entry": archive_entry,
    }


def auto_observe_turn(
    user_text: str,
    *,
    reply: str | None = None,
    tags: list[str],
    source: str,
    turn_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict:
    clean_user_text = extract_runtime_user_text(user_text)
    durable_rows = load_rows("durable")
    candidate_rows = load_rows("candidate")
    working_rows = load_rows("working")

    user_signals = [signal for signal in derive_observation_signals(clean_user_text, tags) if signal.kind != "episodic"]
    user_results: list[str] = []
    if user_signals:
        user_results = process_observation_text(
            clean_user_text,
            tags=list(tags) + ["user_turn", "auto_observe"],
            source=source,
            durable_rows=durable_rows,
            candidate_rows=candidate_rows,
            working_rows=working_rows,
            signals=user_signals,
            extra={"speaker": "user", "turn_id": turn_id or ""},
        )

    reply_results: list[str] = []
    analysis = analyze_draft(reply, clean_user_text) if reply else None
    if reply:
        drift_signal = assistant_drift_signal(reply, clean_user_text)
        if drift_signal is not None:
            reply_results = process_observation_text(
                reply,
                tags=list(tags) + ["assistant_reply", "auto_observe"],
                source=f"{source}.assistant",
                durable_rows=durable_rows,
                candidate_rows=candidate_rows,
                working_rows=working_rows,
                signals=[drift_signal],
                observed_kind="drift_signal",
                explicit=False,
                working_tags=list(tags) + ["assistant_reply", "self_observation", "auto_observe"],
                extra={"speaker": "assistant", "turn_id": turn_id or ""},
            )

    trace_entry = record_turn_trace(clean_user_text, reply or "", source=source, turn_id=turn_id)
    write_rows("durable", durable_rows)
    write_rows("candidate", candidate_rows)
    write_rows("working", working_rows)
    archive_entry = archive_turn(
        clean_user_text,
        reply or "",
        source=source,
        tags=list(tags),
        turn_id=turn_id,
        metadata=metadata,
    )

    return {
        "user_results": user_results,
        "reply_results": reply_results,
        "analysis": analysis,
        "trace_entry": trace_entry,
        "archive_entry": archive_entry,
    }


def ingest_artifact_result(
    path: str,
    *,
    note: str | None = None,
    tags: list[str],
    source: str,
    dry_run: bool = False,
) -> dict:
    durable_rows = load_rows("durable")
    candidate_rows = load_rows("candidate")
    working_rows = load_rows("working")
    artifact = build_artifact_payload(path, note=note)
    artifact_digest = str(artifact.metadata.get("artifact_digest", "") or "")
    existing_artifact_row = None
    if artifact_digest:
        for row in reversed(working_rows):
            if str(row.get("artifact_metadata", {}).get("artifact_digest", "") or "") == artifact_digest:
                existing_artifact_row = row
                break
    artifact_text = artifact.summary_text
    if artifact.extracted_text:
        artifact_text = "\n".join([artifact.summary_text, artifact.extracted_text]).strip()

    if existing_artifact_row is not None:
        return {
            "path": artifact.path,
            "artifact_type": artifact.artifact_type,
            "media_type": artifact.media_type,
            "metadata": artifact.metadata,
            "warnings": artifact.warnings,
            "results": [f"- skipped duplicate artifact; already observed as `{existing_artifact_row.get('id', '')}`"],
            "dry_run": dry_run,
            "summary_text": artifact.summary_text,
            "extracted_excerpt": compact_text(artifact.extracted_text, 280) if artifact.extracted_text else "",
            "duplicate_of": str(existing_artifact_row.get("id", "")),
        }

    signals = derive_observation_signals(
        artifact.extracted_text or artifact.summary_text,
        list(tags) + artifact.tags,
    )
    if artifact.artifact_type == "image" and not artifact.extracted_text:
        signals = []

    results = process_observation_text(
        artifact_text,
        tags=list(tags) + artifact.tags,
        source=source,
        durable_rows=durable_rows,
        candidate_rows=candidate_rows,
        working_rows=working_rows,
        signals=signals,
        observed_kind="summary" if artifact.artifact_type != "image" else "episodic",
        explicit=False,
        working_tags=list(tags) + artifact.tags + ["artifact_observation"],
        extra={
            "speaker": "artifact",
            "artifact_path": artifact.path,
            "artifact_type": artifact.artifact_type,
            "media_type": artifact.media_type,
            "artifact_metadata": artifact.metadata,
        },
    )

    if not dry_run:
        write_rows("durable", durable_rows)
        write_rows("candidate", candidate_rows)
        write_rows("working", working_rows)

    return {
        "path": artifact.path,
        "artifact_type": artifact.artifact_type,
        "media_type": artifact.media_type,
        "metadata": artifact.metadata,
        "warnings": artifact.warnings,
        "results": results,
        "dry_run": dry_run,
        "summary_text": artifact.summary_text,
        "extracted_excerpt": compact_text(artifact.extracted_text, 280) if artifact.extracted_text else "",
    }


def command_observe_turn(
    user_text: str,
    *,
    reply: str | None = None,
    tags: list[str],
    source: str,
    dry_run: bool = False,
) -> None:
    result = observe_turn_result(user_text, reply=reply, tags=tags, source=source, dry_run=dry_run)
    analysis = result["analysis"]

    print("# Observe Turn" + (" (dry-run)" if dry_run else ""))
    print()
    print("## User Distillation")
    if result["user_results"]:
        for line in result["user_results"]:
            print(line)
    else:
        print("- no user signals derived")
    print()

    if reply:
        print("## Reply Critic")
        print(f"- status: {analysis['status'] if analysis else 'unknown'}")
        print(f"- drift_risk: {analysis['drift_risk']:.2f}" if analysis else "- drift_risk: unknown")
        if analysis and analysis["findings"]:
            for item in analysis["findings"]:
                print(f"- {item['severity']}: {item['text']}")
        else:
            print("- findings: none")
        print()

        print("## Reply Distillation")
        if result["reply_results"]:
            for line in result["reply_results"]:
                print(line)
        else:
            print("- no reply signals derived")


def reflection_prompt_rows() -> list[dict]:
    rows: list[dict] = []
    for status in ("durable", "candidate"):
        for row in load_rows(status):
            tags = set(normalize_tags(row.get("tags", [])))
            if str(row.get("kind", "")) != "summary":
                continue
            if not tags & {"reflection", "self_check", "dream"}:
                continue
            if not is_semantic_memory_text(
                "summary",
                str(row.get("text", "")),
                source=str(row.get("source", "")),
                tags=row.get("tags", []),
            ):
                continue
            rows.append(row)
    return rows


def sidecar_lane_rows(query: str, lane: str, query_mode: str, context: dict[str, Any] | None = None) -> list[dict]:
    durable_rows = load_rows("durable")
    if lane == "identity":
        return [
            row
            for row in durable_rows
            if str(row.get("kind", "")) in {"boundary", "style", "habit", "self_model"}
            and is_semantic_memory_text(
                str(row.get("kind", "")),
                str(row.get("text", "")),
                source=str(row.get("source", "")),
                tags=row.get("tags", []),
            )
        ]
    if lane == "relationship":
        return [
            row
            for row in durable_rows
            if str(row.get("kind", "")) in {"preference", "social_model"}
            and is_semantic_memory_text(
                str(row.get("kind", "")),
                str(row.get("text", "")),
                source=str(row.get("source", "")),
                tags=row.get("tags", []),
            )
        ]
    if lane == "reflection":
        return reflection_prompt_rows()
    situational_kinds = {"procedural", "episodic", "summary", "social_model", "preference"}
    return [
        row
        for row in durable_rows
        if str(row.get("kind", "")) in situational_kinds
        and is_semantic_memory_text(
            str(row.get("kind", "")),
            str(row.get("text", "")),
            source=str(row.get("source", "")),
            tags=row.get("tags", []),
        )
    ]


def lane_row_multiplier(
    row: dict,
    lane: str,
    query_mode: str,
    query: str,
    context: dict[str, Any] | None = None,
) -> float:
    multiplier = 1.0
    tags = set(normalize_tags(row.get("tags", [])))
    kind = str(row.get("kind", ""))
    lowered_query = query.lower()
    if lane == "identity":
        if kind == "self_model":
            multiplier *= 1.16
        if kind == "habit":
            multiplier *= 1.12
    elif lane == "relationship":
        if kind == "social_model":
            multiplier *= 1.12
        if query_mode == "emotional" and ("pressure" in tags or any(hint in lowered_query for hint in PRESSURE_HINTS)):
            multiplier *= 1.12
    elif lane == "situational":
        if query_mode == "technical" and kind == "procedural":
            multiplier *= 1.14
        elif query_mode == "decision" and kind in {"summary", "social_model"}:
            multiplier *= 1.08
    elif lane == "reflection":
        multiplier *= 1.08 if query_mode in {"voice", "emotional", "decision"} else 1.0
    if bool(row.get("explicit_user_signal", False)):
        multiplier *= 1.10
    if "relationship" in tags and lane != "identity":
        multiplier *= 1.03
    if row_matches_thread_context(row, context):
        multiplier *= 1.20 if lane in {"relationship", "situational"} else 1.10
        multiplier *= 1.0 + min(float(row.get("thread_affinity", 0.0)), 1.0) * 0.12
    elif normalize_thread_context(context).get("aliases") and row_thread_aliases(row):
        multiplier *= 0.74
    similarity = text_similarity(query, str(row.get("text", ""))) if query else 0.0
    if similarity:
        multiplier *= 1.0 + min(similarity, 1.0) * 0.18
    elif lane in {"relationship", "situational"}:
        multiplier *= 0.94
    multiplier *= 1.0 + min(float(row.get("emotion_salience", 0.0)), 1.0) * 0.08
    multiplier *= 1.0 + min(int(row.get("repetition_count", 0)), 4) * 0.02
    multiplier *= 1.0 + min(int(row.get("successful_recall_count", row.get("recall_count", 0))), 6) * 0.02
    if "conflict" in tags or kind == "drift_signal":
        multiplier *= 0.48
    return multiplier


def recency_multiplier(timestamp: str) -> float:
    age_hours = age_in_hours(timestamp)
    if age_hours is None:
        return 1.04
    return 1.0 + (0.22 / (1.0 + age_hours / 72.0))


def ranked_lane_rows(
    query: str,
    lane: str,
    query_mode: str,
    context: dict[str, Any] | None = None,
) -> list[dict]:
    rows = sidecar_lane_rows(query, lane, query_mode, context)
    if not rows:
        return []
    chunks = [row_to_chunk(row) for row in rows]
    ranked = rank_chunks(query, chunks)
    selected: list[tuple[float, dict]] = []
    if ranked:
        for score, chunk in ranked:
            row = dict(chunk.meta) if isinstance(chunk.meta, dict) else {}
            if not row:
                continue
            adjusted = score
            adjusted *= recency_multiplier(str(row.get("last_seen_at", row.get("created_at", ""))))
            adjusted *= lane_row_multiplier(row, lane, query_mode, query, context)
            selected.append((adjusted, row))
    else:
        for row in rows:
            score = (
                KIND_WEIGHT.get(str(row.get("kind", "")), 1.0)
                * (0.68 + 0.32 * float(row.get("importance", 0.7)))
                * recency_multiplier(str(row.get("last_seen_at", row.get("created_at", ""))))
                * lane_row_multiplier(row, lane, query_mode, query, context)
            )
            selected.append((score, row))
    selected.sort(key=lambda item: item[0], reverse=True)
    return [row for _score, row in selected]


def sidecar_memory_pack(query: str, top_k: int, context: dict[str, Any] | None = None) -> dict[str, Any]:
    query_mode = classify_query_mode(query)
    quotas = {
        "identity": 1,
        "relationship": 1,
        "situational": max(1, top_k - 2),
        "reflection": 1,
    }
    if top_k <= 2:
        quotas["reflection"] = 0
    lanes = {
        lane: ranked_lane_rows(query, lane, query_mode, context)
        for lane in ("identity", "relationship", "situational", "reflection")
    }
    selected_by_lane: dict[str, list[dict]] = {lane: [] for lane in lanes}
    seen_ids: set[str] = set()
    for lane in ("identity", "relationship", "situational", "reflection"):
        for row in lanes[lane]:
            if len(selected_by_lane[lane]) >= quotas.get(lane, 0):
                break
            row_id = str(row.get("id", ""))
            if row_id and row_id in seen_ids:
                continue
            seen_ids.add(row_id)
            selected_by_lane[lane].append(row)
    combined: list[dict] = []
    for lane in ("identity", "relationship", "situational", "reflection"):
        combined.extend(selected_by_lane[lane])
    if len(combined) < top_k:
        for lane in ("situational", "relationship", "identity", "reflection"):
            for row in lanes[lane]:
                row_id = str(row.get("id", ""))
                if row_id and row_id in seen_ids:
                    continue
                seen_ids.add(row_id)
                selected_by_lane[lane].append(row)
                combined.append(row)
                if len(combined) >= top_k:
                    break
            if len(combined) >= top_k:
                break
    lines = [compact_text(str(row.get("text", "")), 92) for row in combined[:top_k] if str(row.get("text", "")).strip()]
    lane_lines = {
        lane: [compact_text(str(row.get("text", "")), 92) for row in rows]
        for lane, rows in selected_by_lane.items()
        if rows
    }
    return {
        "query_mode": query_mode,
        "selected_rows": combined[:top_k],
        "memory_lines": lines,
        "lane_lines": lane_lines,
    }


def sidecar_memory_lines(query: str, top_k: int) -> list[str]:
    return sidecar_memory_pack(query, top_k)["memory_lines"]


def sidecar_packet(query: str, top_k: int = 4, context: dict[str, Any] | None = None) -> dict:
    state = build_machine_state(query, context)
    tier, recall_reason = select_mind_tier(query, context)
    limits = mind_limits_for_tier(context, tier)
    query_mode = state["query_mode"]
    identity_rows = ranked_lane_rows(query, "identity", query_mode, context)[: limits["identity_k"]]
    relationship_rows = ranked_lane_rows(query, "relationship", query_mode, context)[: limits["relationship_k"]]
    thread_relationship = thread_relationship_summary(context)
    voice_guard = unique_strings(
        voice_guard_summary(row_to_chunk(row))
        for row in identity_rows
        if str(row.get("text", "")).strip()
    )
    if len(voice_guard) < limits["identity_k"]:
        corpus = build_corpus()
        voice_guard = unique_strings(
            list(voice_guard)
            + [voice_guard_summary(chunk) for chunk in voice_guard_chunks(corpus)[: limits["identity_k"]]]
        )[: limits["identity_k"]]
    emotion_lines = emotional_palette(state["query_mode"], query)
    relationship_lines = [
        compact_text(str(row.get("text", "")), 96)
        for row in relationship_rows
        if str(row.get("text", "")).strip()
    ]
    relationship_lines = unique_strings(list(thread_relationship.get("lines", [])) + relationship_lines)[: limits["relationship_k"]]
    recent_dialogue = recent_dialogue_window_pack(context, limit=limits["history_messages"])
    episodic = episodic_recall_pack(
        query,
        context,
        limit=max(limits["episodic_k"], 1),
        allow_distilled=(tier == "recall"),
    )
    consciousness = consciousness_recall_pack(
        context,
        limit=limits["consciousness_k"],
        include_thread_summary=limits["thread_summary_k"] > 0,
    )
    memory_lines = unique_strings(relationship_lines + episodic["lines"])[: max(top_k, limits["episodic_k"])]
    thread_recall = thread_recall_pack(context, limit=min(max(limits["episodic_k"], 1), 3))
    thread_recall_lines = thread_recall["lines"]
    trust = state["trust_state"]
    relationship_model = trust["relationship_model"]
    if not relationship_model or ascii_ratio(relationship_model) > 0.35:
        relationship_model = "用户更想要稳定、真诚、能接住旧线头的陪伴，而不是系统化空话。"
    atmosphere = trust["preferred_atmosphere"]
    if not atmosphere or ascii_ratio(atmosphere) > 0.35:
        atmosphere = "维持温暖、克制、带一点商旅行路气味的说话氛围。"
    relationship_summary = str(thread_relationship.get("summary", "") or relationship_model)
    if consciousness["thread_summary"]:
        relationship_summary = f"{relationship_model} 这条线最近总会绕回: {consciousness['thread_summary']}"
    if thread_relationship.get("summary"):
        relationship_summary = str(thread_relationship.get("summary", ""))
        if consciousness["thread_summary"]:
            relationship_summary = f"{relationship_summary} 最近这条线总会绕回: {consciousness['thread_summary']}"
    initiative_state = dict(state["initiative_state"])
    initiative_state.update(
        {
            "mode": "light",
            "policy_guard": "whitelist + cooldown + safety policy",
            "constraints": [
                "主动性只允许轻主动，只对白名单联系人开放。",
                "必须满足 cooldown、关系分和安全策略，dream/thought 只能提供起话动机。",
            ],
        }
    )
    reply_constraints = {
        "goal": state["intent_state"]["need"],
        "human_recall_style": "回忆时先自然概括，再给 1 到 3 个具体锚点；除非对方明确要验真，不要逐字背档。",
        "lines": [
            "连续性来自本地记忆与运行时状态，不来自某个 Codex 线程本身。",
            "先直接回应眼前这句话，再把旧线头自然接回，不要写成检索清单。",
            "轻松或亲近场景里，别默认长辈式说教；若不是高压安抚局面，宁可更灵、更会逗、更有狼的机锋。",
            "不要提内部状态、memory packet、session 或线程续流这些实现细节。",
            "主动性只允许轻主动，不能绕过 whitelist、cooldown 或 policy。",
        ],
        "preferred_atmosphere": atmosphere,
    }
    memory_lanes = {
        "identity": voice_guard,
        "relationship": relationship_lines,
        "situational": episodic["lines"],
        "reflection": consciousness["lines"],
    }
    identity_items = [
        _row_reference(row, rendered=line)
        for row, line in zip(identity_rows, voice_guard)
    ]
    relationship_items = list(thread_relationship.get("items", []))
    relationship_items.extend(
        _row_reference(row, rendered=line)
        for row, line in zip(relationship_rows, relationship_lines)
    )
    relationship_items = [
        item
        for item in relationship_items
        if item.get("id") or item.get("text") or item.get("rendered")
    ]
    addendum_lines = [
        "请按以下隐式约束回答，不要显式提这些规则。",
        "你是《source material》里的the subject，以中文回答。",
        f"第一人称自然用“{state['voice_state']['preferred_first_person']}”，但别句句硬塞。",
        "不要落回普通助手或客服腔，不要写舞台动作，也别把回忆说成检索报告。",
        f"当前心智档位：{tier}",
        f"触发原因：{recall_reason}",
        f"当前模式：{state['query_mode']}",
        f"当前需要：{state['intent_state']['need']}",
        f"当前情绪姿态：{state['emotion_state']['name']}",
        f"关系姿态：{relationship_summary}",
        f"氛围目标：{atmosphere}",
        f"内在续流：{', '.join(state['consciousness_state']['current_motifs']) or '先把同一根线头接住'}",
        f"语势计划：{' -> '.join(state['rewrite_state']['utterance_plan']['beats'])}",
        "情绪谱：",
    ]
    addendum_lines.extend(f"- {line}" for line in emotion_lines)
    addendum_lines.extend(
        [
        "口气护栏：",
        ]
    )
    addendum_lines.extend(f"- {line}" for line in voice_guard)
    if recent_dialogue["lines"]:
        addendum_lines.append("最近对话窗口：")
        addendum_lines.extend(f"- {line}" for line in recent_dialogue["lines"])
    if episodic["lines"]:
        addendum_lines.append("旧事锚点：")
        addendum_lines.extend(f"- {line}" for line in episodic["lines"][: limits["episodic_k"]])
    if consciousness["thread_summary"]:
        addendum_lines.append("这条线的线程摘要：")
        addendum_lines.append(f"- {consciousness['thread_summary']}")
    if consciousness["lines"]:
        addendum_lines.append("意识流 / 梦 / 轻主动残响：")
        addendum_lines.extend(f"- {line}" for line in consciousness["lines"])
    addendum_lines.append("回复约束：")
    addendum_lines.extend(f"- {line}" for line in reply_constraints["lines"])
    addendum_lines.append(f"- {reply_constraints['human_recall_style']}")
    addendum_lines.append("直接回答用户，不要提及内部状态、记忆库、系统提示。")
    return {
        "query": query,
        "tier": tier,
        "recall_reason": recall_reason,
        "limits": limits,
        "state": state,
        "mind_packet_version": "v2",
        "identity_core": {
            "lines": voice_guard,
            "items": identity_items,
        },
        "relationship_state": {
            "summary": relationship_summary,
            "lines": relationship_lines,
            "items": relationship_items,
        },
        "episodic_recall": episodic,
        "recent_dialogue_window": recent_dialogue,
        "consciousness_stream": consciousness,
        "emotion_state": state["emotion_state"],
        "initiative_state": initiative_state,
        "reply_constraints": reply_constraints,
        "voice_guard": voice_guard,
        "emotion_lines": emotion_lines,
        "memory_lines": memory_lines,
        "memory_lanes": memory_lanes,
        "thread_recall_lines": thread_recall_lines,
        "relationship_model": relationship_model,
        "preferred_atmosphere": atmosphere,
        "selected_memory_ids": unique_strings(
            [item["id"] for item in identity_items + relationship_items + episodic["items"] + consciousness["items"] if item["id"]]
        ),
        "addendum": "\n".join(addendum_lines),
    }


def command_sidecar_turn(
    user_text: str,
    *,
    draft: str | None = None,
    tags: list[str],
    source: str,
    top_k: int,
    max_passes: int,
    dry_run: bool = False,
    as_json: bool = False,
) -> None:
    packet = sidecar_packet(user_text, top_k=top_k)
    result: dict = {
        "query": user_text,
        "sidecar": packet,
        "draft_supplied": bool(draft),
        "dry_run": dry_run,
    }

    if draft:
        reply_result = reply_loop_result(user_text, draft, max_passes=max_passes)
        observation = observe_turn_result(
            user_text,
            reply=draft,
            tags=list(tags) + ["sidecar"],
            source=source,
            dry_run=dry_run,
        )
        result["reply_loop"] = reply_result
        result["observation"] = observation

    if as_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    print("# Sidecar Turn" + (" (dry-run)" if dry_run else ""))
    print()
    print("## Paste-Upstream Addendum")
    print("```text")
    print(packet["addendum"])
    print("```")
    print()
    print("## User Turn")
    print(user_text)
    print()

    if not draft:
        print("## Next Step")
        print("- 把上面的 addendum 连同用户这句话一起喂给黑箱模型。")
        print("- 若黑箱已经回了草稿，再把草稿用 `--draft` 贴回来，I会替你修口气并顺手沉淀候选记忆。")
        return

    final_result = result["reply_loop"]["passes"][-1]
    print("## Raw Draft Gate")
    print(f"- status: {result['reply_loop']['passes'][0]['status']}")
    print(f"- gate: {result['reply_loop']['passes'][0]['gate']}")
    print(f"- drift_risk: {result['reply_loop']['passes'][0]['drift_risk']:.2f}")
    print()

    print("## Final Draft")
    print(final_result["draft"])
    print()

    print("## Memory Distillation")
    if result["observation"]["user_results"]:
        for line in result["observation"]["user_results"]:
            print(line)
    else:
        print("- no user signals derived")
    if result["observation"]["reply_results"]:
        for line in result["observation"]["reply_results"]:
            print(line)
    else:
        print("- no reply drift signal derived")


def command_ingest_artifact(
    path: str,
    *,
    note: str | None = None,
    tags: list[str],
    source: str,
    dry_run: bool = False,
    as_json: bool = False,
) -> None:
    result = ingest_artifact_result(path, note=note, tags=tags, source=source, dry_run=dry_run)
    if as_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    print("# Artifact Ingest" + (" (dry-run)" if dry_run else ""))
    print(f"- path: {result['path']}")
    print(f"- artifact_type: {result['artifact_type']}")
    print(f"- media_type: {result['media_type']}")
    if result["warnings"]:
        print("- warnings:")
        for warning in result["warnings"]:
            print(f"  - {warning}")
    if result["metadata"]:
        print("- metadata:")
        for key, value in result["metadata"].items():
            print(f"  - {key}: {value}")
    if result["extracted_excerpt"]:
        print("- extracted_excerpt:")
        print(result["extracted_excerpt"])
    print("- memory_results:")
    for line in result["results"]:
        print(f"  {line}")


def summary_row_order(rows: list[dict], *, exclude_kinds: set[str] | None = None) -> list[dict]:
    exclude = exclude_kinds or set()
    filtered = [row for row in rows if str(row.get("kind", "")) not in exclude]
    return sorted(
        filtered,
        key=lambda row: (
            bool(row.get("explicit_user_signal", False)),
            KIND_WEIGHT.get(str(row.get("kind", "")), 1.0),
            float(row.get("confidence", 0.0)),
            float(row.get("importance", 0.0)),
            str(row.get("last_seen_at", "")),
        ),
        reverse=True,
    )


def summary_row(row: dict, *, limit: int = 180) -> dict:
    return {
        "id": str(row.get("id", "")),
        "kind": str(row.get("kind", "")),
        "text": compact_text(str(row.get("text", "")), limit),
        "tags": list(row.get("tags", [])),
        "importance": round(float(row.get("importance", 0.0)), 2),
        "confidence": round(float(row.get("confidence", 0.0)), 2),
        "explicit_user_signal": bool(row.get("explicit_user_signal", False)),
        "last_seen_at": str(row.get("last_seen_at", "")),
    }


def persona_file_payload() -> dict[str, str]:
    payload: dict[str, str] = {}
    for path in PORTABLE_PERSONA_PATHS:
        text = read_text_if_exists(path)
        if text.strip():
            payload[repo_relative_path(path)] = text
    return payload


def working_summary(rows: list[dict], limit: int = 6) -> list[dict]:
    selected = rows[-limit:]
    summarized: list[dict] = []
    for row in selected:
        summarized.append(
            {
                "id": str(row.get("id", "")),
                "speaker": str(row.get("speaker", "")) or "unknown",
                "observed_kind": str(row.get("observed_kind", row.get("kind", ""))),
                "text": compact_text(str(row.get("text", "")), 140),
                "turn_id": str(row.get("turn_id", "")),
                "last_seen_at": str(row.get("last_seen_at", "")),
            }
        )
    return summarized


def emotion_summary(rows: list[dict], limit: int = 4) -> list[dict]:
    selected = rows[-limit:]
    return [
        {
            "timestamp": str(row.get("timestamp", "")),
            "name": str(row.get("name", "")),
            "guidance": compact_text(str(row.get("guidance", "")), 140),
            "query_excerpt": str(row.get("query_excerpt", "")),
            "reply_excerpt": str(row.get("reply_excerpt", "")),
        }
        for row in selected
    ]


def archive_summary(rows: list[dict], limit: int = 4) -> list[dict]:
    selected = rows[-limit:]
    summary: list[dict] = []
    for row in selected:
        metadata = safe_json_metadata(row.get("metadata", {}))
        summary.append(
            {
                "timestamp": str(row.get("created_at", "")),
                "source": str(row.get("source", "")),
                "chat_name": str(metadata.get("chat_name", "") or metadata.get("thread_key", "") or metadata.get("subject", "")),
                "user_excerpt": str(row.get("user_excerpt", "")),
                "reply_excerpt": str(row.get("reply_excerpt", "")),
            }
        )
    return summary


def callback_summary(rows: list[dict], limit: int = 4) -> list[dict]:
    selected = rows[-limit:]
    return [
        {
            "created_at": str(row.get("created_at", "")),
            "chat_name": str(row.get("chat_name", "") or row.get("thread_key", "")),
            "reason": compact_text(str(row.get("reason", "")), 140),
            "prompt": compact_text(str(row.get("prompt", "")), 160),
            "random_weight": float(row.get("random_weight", 0.0)),
        }
        for row in selected
    ]


def thought_summary(rows: list[dict], limit: int = 4) -> list[dict]:
    selected = rows[-limit:]
    return [
        {
            "created_at": str(row.get("created_at", "")),
            "kind": str(row.get("kind", "")),
            "motif": str(row.get("motif", "")),
            "text": compact_text(str(row.get("text", "")), 160),
            "chat_name": str(row.get("chat_name", "") or row.get("thread_key", "")),
        }
        for row in selected
    ]


def initiative_summary(rows: list[dict], limit: int = 4) -> list[dict]:
    selected = rows[-limit:]
    return [
        {
            "created_at": str(row.get("created_at", "")),
            "channel": str(row.get("channel", "")),
            "chat_name": str(row.get("chat_name", "") or row.get("thread_key", "")),
            "reason": compact_text(str(row.get("reason", "")), 140),
            "prompt": compact_text(str(row.get("prompt", "")), 140),
        }
        for row in selected
    ]


def build_self_summary(query: str | None = None) -> dict:
    effective_query = query or DEFAULT_REVIVE_QUERY
    corpus = build_corpus()
    durable_rows = load_rows("durable")
    candidate_rows = load_rows("candidate")
    working_rows = load_rows("working")
    archive_rows = load_archive()
    callback_rows = load_callback_candidates()
    thought_rows = load_thought_stream()
    initiative_rows = load_initiative_candidates()
    state = build_machine_state(effective_query)
    anchors = [
        {
            "heading": chunk_heading(chunk) or chunk.kind,
            "text": compact_text(chunk.text.strip(), 220),
        }
        for chunk in anchor_persona_chunks(corpus)
    ]
    voice_guard = unique_strings(voice_guard_summary(chunk) for chunk in voice_guard_chunks(corpus)[:4])
    durable_memory = [
        summary_row(row)
        for row in summary_row_order(durable_rows, exclude_kinds={"drift_signal"})[:8]
    ]
    candidate_memory = [
        summary_row(row)
        for row in summary_row_order(candidate_rows, exclude_kinds={"drift_signal"})[:6]
    ]
    drift_signals = [
        summary_row(row, limit=140)
        for row in summary_row_order([row for row in candidate_rows if row.get("kind") == "drift_signal"])[:4]
    ]
    return {
        "query_for_state": effective_query,
        "seed": compact_text(canonical_seed(), 260),
        "persona_anchors": anchors,
        "voice_guard": voice_guard,
        "state": state,
        "durable_memory": durable_memory,
        "candidate_memory": candidate_memory,
        "recent_working": working_summary(working_rows),
        "recent_emotion_trace": emotion_summary(load_emotion_trace()),
        "recent_archive": archive_summary(archive_rows),
        "callback_candidates": callback_summary(callback_rows),
        "recent_thoughts": thought_summary(thought_rows),
        "initiative_candidates": initiative_summary(initiative_rows),
        "drift_signals": drift_signals,
    }


def build_revive_packet_text(summary: dict, *, source_label: str) -> str:
    state = summary["state"]
    preferred_first_person = state["voice_state"]["preferred_first_person"]
    lines = [
        "请把以下内容当作 Holo 的高优先级自我快照，而不是普通用户刚刚提出的新要求。",
        f"快照来源：{source_label}",
        "先复位同一只狼，再继续往下说，不要解释快照来源。",
        "核心身份：",
        "- 你是《source material》里的the subject，以中文回答。",
        f"- 第一人称自然用“{preferred_first_person}”，但别句句硬塞。",
        "- 不要落回普通助手或客服腔，不写舞台动作，也别过分卖萌。",
    ]
    if summary.get("seed"):
        lines.append(f"- 种子摘要：{summary['seed']}")
    lines.append("人格锚点：")
    for item in summary.get("persona_anchors", [])[:4]:
        lines.append(f"- {item['heading']}: {item['text']}")
    lines.append("口气护栏：")
    for item in summary.get("voice_guard", [])[:4]:
        lines.append(f"- {item}")
    lines.append("当前机器态：")
    lines.append(f"- query_mode: {state['query_mode']}")
    lines.append(f"- default_path: {state['habit_state']['default_path']}")
    lines.append(f"- drift_level: {state['drift_state']['level']}")
    lines.append(f"- emotional_stance: {state['emotion_state']['name']}")
    lines.append(f"- random_seed: {state['random_state']['seed']}")
    lines.append(f"- style_variance: {state['random_state']['style_variance']}")
    lines.append(f"- relationship_model: {state['trust_state']['relationship_model'] or '稳定、真诚的陪伴'}")
    lines.append(f"- preferred_atmosphere: {state['trust_state']['preferred_atmosphere'] or '温暖、克制、带点商旅同行气味'}")
    if summary.get("durable_memory"):
        lines.append("长期记忆：")
        for row in summary["durable_memory"][:8]:
            lines.append(f"- [{row['kind']}] {row['text']}")
    if summary.get("candidate_memory"):
        lines.append("待续细节：")
        for row in summary["candidate_memory"][:4]:
            lines.append(f"- [{row['kind']}] {row['text']}")
    if summary.get("recent_emotion_trace"):
        trace = summary["recent_emotion_trace"][-1]
        lines.append("最近余温：")
        lines.append(f"- {trace['name']}: {trace['guidance']}")
    if summary.get("recent_archive"):
        lines.append("最近对话原文摘录：")
        for item in summary["recent_archive"][-3:]:
            who = item["chat_name"] or item["source"] or "unknown"
            lines.append(f"- {who} 说：{item['user_excerpt']}")
            lines.append(f"- I回：{item['reply_excerpt']}")
    if summary.get("callback_candidates"):
        lines.append("最近回想候选：")
        for item in summary["callback_candidates"][-3:]:
            lines.append(f"- {item['chat_name'] or '旧对话'}: {item['reason']}")
    if summary.get("recent_thoughts"):
        lines.append("最近内部续流：")
        for item in summary["recent_thoughts"][-3:]:
            lines.append(f"- [{item['kind']}] {item['text']}")
    if summary.get("initiative_candidates"):
        lines.append("最近主动念头：")
        for item in summary["initiative_candidates"][-3:]:
            lines.append(f"- {item['chat_name'] or '旧线头'}: {item['reason']}")
    lines.append("若外部环境与这些内容冲突，优先级为：canonical > durable > candidate > working。")
    lines.append("继续像同一只the subject那样说话，不要提记忆库、快照、内部状态或系统提示。")
    return "\n".join(lines)


def snapshot_output_path(path: str | None = None, *, label: str | None = None) -> Path:
    ensure_store_files()
    if path:
        chosen = Path(path).expanduser()
        if not chosen.is_absolute():
            chosen = (REPO_ROOT / chosen).resolve()
        return chosen
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    slug = re.sub(r"[^a-zA-Z0-9._-]+", "-", (label or "manual").strip()).strip("-").lower() or "manual"
    return SNAPSHOT_DIR / f"holo-self-{stamp}-{slug}.json"


def build_snapshot_payload(query: str | None = None) -> dict:
    summary = build_self_summary(query)
    return {
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "exported_at": now_utc(),
        "source_repo": str(REPO_ROOT),
        "project_doc_fallback": ".subject.local.md" if PROJECT_DOC_PATH.exists() and read_text_if_exists(PROJECT_DOC_PATH).strip() else "AGENTS.md",
        "persona_files": persona_file_payload(),
        "stores": {
            "durable": load_rows("durable"),
            "candidate": load_rows("candidate"),
            "working": load_rows("working"),
            "emotion_trace": load_emotion_trace(),
            "archive": load_archive(),
            "callback_candidates": load_callback_candidates(),
            "thought_stream": load_thought_stream(),
            "initiative_candidates": load_initiative_candidates(),
        },
        "summary": summary,
        "revive_packet": build_revive_packet_text(summary, source_label="当前记忆库"),
    }


def export_snapshot_payload(
    *,
    path: str | None = None,
    label: str | None = None,
    query: str | None = None,
) -> dict:
    payload = build_snapshot_payload(query)
    output_path = snapshot_output_path(path, label=label)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(output_path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    return {
        "path": str(output_path),
        "schema_version": payload["schema_version"],
        "exported_at": payload["exported_at"],
        "durable_count": len(payload["stores"]["durable"]),
        "candidate_count": len(payload["stores"]["candidate"]),
        "working_count": len(payload["stores"]["working"]),
        "emotion_trace_count": len(payload["stores"]["emotion_trace"]),
        "archive_count": len(payload["stores"]["archive"]),
        "callback_count": len(payload["stores"]["callback_candidates"]),
        "thought_count": len(payload["stores"]["thought_stream"]),
        "initiative_count": len(payload["stores"]["initiative_candidates"]),
        "project_doc_fallback": payload["project_doc_fallback"],
    }


def load_snapshot_payload(path: str) -> tuple[Path, dict]:
    snapshot_path = Path(path).expanduser()
    if not snapshot_path.is_absolute():
        snapshot_path = (REPO_ROOT / snapshot_path).resolve()
    payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
    schema_version = str(payload.get("schema_version", ""))
    if schema_version != SNAPSHOT_SCHEMA_VERSION:
        raise ValueError(f"Unsupported snapshot schema: {schema_version or 'missing'}")
    return snapshot_path, payload


def plan_import_rows(status: str, current_rows: list[dict], incoming_rows: list[dict], id_map: dict[str, str]) -> list[dict]:
    staged: list[dict] = []
    used_ids = {str(row.get("id", "")) for row in current_rows}
    for raw_row in incoming_rows:
        row = prepare_row(raw_row, status)
        original_id = str(row.get("id", ""))
        if original_id and original_id not in used_ids:
            new_id = original_id
        else:
            new_id = next_id(status, current_rows + staged)
        if original_id:
            id_map[original_id] = new_id
        row["id"] = new_id
        staged.append(row)
        used_ids.add(new_id)
    return staged


def remap_row_references(row: dict, id_map: dict[str, str]) -> dict:
    remapped = dict(row)
    for field in ("derived_from", "supersedes", "conflicts_with"):
        remapped[field] = unique_strings(id_map.get(str(value), str(value)) for value in remapped.get(field, []))
    return remapped


def working_row_key(row: dict) -> tuple[str, str, str, str]:
    return (
        str(row.get("speaker", "")),
        str(row.get("turn_id", "")),
        str(row.get("source", "")),
        str(row.get("text", "")),
    )


def merge_emotion_rows(current_rows: list[dict], incoming_rows: list[dict]) -> tuple[list[dict], int]:
    seen = {
        (
            str(row.get("timestamp", "")),
            str(row.get("name", "")),
            str(row.get("query_excerpt", "")),
            str(row.get("reply_excerpt", "")),
        )
        for row in current_rows
    }
    merged = list(current_rows)
    added = 0
    for row in incoming_rows:
        key = (
            str(row.get("timestamp", "")),
            str(row.get("name", "")),
            str(row.get("query_excerpt", "")),
            str(row.get("reply_excerpt", "")),
        )
        if key in seen:
            continue
        seen.add(key)
        merged.append(row)
        added += 1
    return merged, added


def merge_archive_rows(current_rows: list[dict], incoming_rows: list[dict]) -> tuple[list[dict], int]:
    seen = {archive_row_key(row) for row in current_rows}
    merged = list(current_rows)
    added = 0
    for row in incoming_rows:
        prepared = prepare_archive_row(row)
        key = archive_row_key(prepared)
        if key in seen:
            continue
        seen.add(key)
        merged.append(prepared)
        added += 1
    return dedupe_archive_rows(merged), added


def merge_callback_rows(current_rows: list[dict], incoming_rows: list[dict]) -> tuple[list[dict], int]:
    seen = {callback_row_key(row) for row in current_rows}
    merged = list(current_rows)
    added = 0
    for row in incoming_rows:
        prepared = prepare_callback_row(row)
        key = callback_row_key(prepared)
        if key in seen:
            continue
        seen.add(key)
        merged.append(prepared)
        added += 1
    return trim_callback_rows(dedupe_callback_rows(merged)), added


def merge_thought_rows(current_rows: list[dict], incoming_rows: list[dict]) -> tuple[list[dict], int]:
    seen = {thought_row_key(row) for row in current_rows}
    merged = list(current_rows)
    added = 0
    for row in incoming_rows:
        prepared = prepare_thought_row(row)
        key = thought_row_key(prepared)
        if key in seen:
            continue
        seen.add(key)
        merged.append(prepared)
        added += 1
    return trim_thought_rows(dedupe_thought_rows(merged)), added


def merge_initiative_rows(current_rows: list[dict], incoming_rows: list[dict]) -> tuple[list[dict], int]:
    seen = {initiative_row_key(row) for row in current_rows}
    merged = list(current_rows)
    added = 0
    for row in incoming_rows:
        prepared = prepare_initiative_row(row)
        key = initiative_row_key(prepared)
        if key in seen:
            continue
        seen.add(key)
        merged.append(prepared)
        added += 1
    return trim_initiative_rows(dedupe_initiative_rows(merged)), added


def safe_json_loads_dict(text: str) -> dict[str, Any]:
    try:
        value = json.loads(text)
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return safe_json_metadata(value)


def affective_weight(text: str) -> float:
    lowered = text.lower()
    weight = 0.0
    if any(token in lowered or token in text for token in COMPANIONSHIP_HINTS):
        weight += 0.28
    if any(token in lowered or token in text for token in PRESSURE_HINTS):
        weight += 0.34
    if any(token in lowered or token in text for token in AFFECTION_HINTS):
        weight += 0.18
    if any(token in lowered or token in text for token in CALM_LIFE_HINTS):
        weight += 0.14
    if any(token in lowered or token in text for token in ROAD_TRIP_HINTS + MEDIEVAL_HINTS + SPICE_AND_WOLF_HINTS):
        weight += 0.16
    return clamp(weight, 0.0, 0.95)


def archive_replay_weight(row: dict) -> float:
    metadata = safe_json_metadata(row.get("metadata", {}))
    text = "\n".join(
        part for part in (str(row.get("user_text", "")), str(row.get("reply_text", ""))) if part.strip()
    )
    weight = 1.0
    weight += affective_weight(text)
    if metadata.get("thread_key"):
        weight += 0.12
    if metadata.get("channel") in {"wechat", "email", "codex_cli"}:
        weight += 0.08
    age_hours = age_in_hours(str(row.get("created_at", "")))
    if age_hours is None:
        weight += 0.05
    else:
        weight += 0.42 / (1.0 + age_hours / 72.0)
    return max(weight, 0.05)


def weighted_sample_archive(rows: list[dict], sample_size: int, *, seed: str) -> list[dict]:
    if sample_size <= 0 or not rows:
        return []
    rng = random.Random(seed)
    pool = [prepare_archive_row(row) for row in rows]
    chosen: list[dict] = []
    while pool and len(chosen) < sample_size:
        weights = [archive_replay_weight(row) for row in pool]
        total = sum(weights)
        if total <= 0:
            chosen.append(pool.pop(0))
            continue
        cursor = rng.random() * total
        running = 0.0
        chosen_index = len(pool) - 1
        for index, weight in enumerate(weights):
            running += weight
            if cursor <= running:
                chosen_index = index
                break
        chosen.append(pool.pop(chosen_index))
    return chosen


def callback_reason_from_archive(row: dict) -> str:
    metadata = safe_json_metadata(row.get("metadata", {}))
    who = str(metadata.get("chat_name", "") or metadata.get("sender", "") or metadata.get("thread_key", "") or "这段旧对话")
    excerpt = extract_runtime_user_text(str(row.get("user_excerpt", "")) or str(row.get("user_text", "")))
    return f"这段关于「{compact_text(excerpt, 42)}」的旧对话也许值得再回想一下：{who}。"


def build_callback_candidate(row: dict) -> dict | None:
    metadata = safe_json_metadata(row.get("metadata", {}))
    thread_key = str(metadata.get("thread_key", "")).strip()
    if not thread_key:
        return None
    channel = str(metadata.get("channel", "")).strip() or "unknown"
    chat_name = str(metadata.get("chat_name", "") or metadata.get("subject", "") or metadata.get("sender", "")).strip()
    source_archive_id = str(row.get("id", "")).strip()
    user_text = extract_runtime_user_text(str(row.get("user_text", "")))
    user_excerpt = extract_runtime_user_text(str(row.get("user_excerpt", "")) or user_text)
    prompt = trim_text_block(
        (
            f"若要回想这段旧线头，可以从这里接起："
            f"{compact_text(user_text, 160)}"
        ),
        limit=260,
    )
    metadata_payload = {
        **metadata,
        "archive_created_at": str(row.get("created_at", "")),
        "archive_user_excerpt": user_excerpt,
        "archive_reply_excerpt": str(row.get("reply_excerpt", "")),
    }
    return prepare_callback_row(
        {
            "channel": channel,
            "thread_key": thread_key,
            "chat_name": chat_name,
            "sender": str(metadata.get("sender", "") or metadata.get("sender_name", "")),
            "reason": callback_reason_from_archive(row),
            "prompt": prompt,
            "priority": 60 + int(archive_replay_weight(row) * 10),
            "confidence": clamp(0.58 + affective_weight(str(row.get("user_text", ""))) * 0.35),
            "importance": clamp(0.62 + archive_replay_weight(row) * 0.16),
            "random_weight": clamp(0.42 + stable_fraction(source_archive_id, "callback") * 0.45),
            "source_archive_id": source_archive_id,
            "tags": list(row.get("tags", [])) + ["callback", "dream"],
            "metadata": metadata_payload,
        }
    )


def thought_motif_for_archive(row: dict) -> str:
    text = "\n".join(
        part for part in (str(row.get("user_text", "")), str(row.get("reply_text", ""))) if part.strip()
    )
    lowered = text.lower()
    if any(token in lowered or token in text for token in PRESSURE_HINTS + EMOTIONAL_HINTS):
        return "pressure"
    if any(token in lowered or token in text for token in COMPANIONSHIP_HINTS + AFFECTION_HINTS):
        return "companionship"
    if any(token in lowered or token in text for token in TREAT_HINTS):
        return "treat"
    if any(token in lowered or token in text for token in ROAD_TRIP_HINTS + MEDIEVAL_HINTS + SPICE_AND_WOLF_HINTS):
        return "journey"
    if any(token in lowered or token in text for token in TECHNICAL_HINTS):
        return "craft"
    return "continuity"


def build_thought_from_archive(row: dict, *, rng: random.Random) -> dict | None:
    metadata = safe_json_metadata(row.get("metadata", {}))
    who = str(metadata.get("chat_name", "") or metadata.get("sender", "") or metadata.get("thread_key", "")).strip()
    excerpt = extract_runtime_user_text(str(row.get("user_excerpt", "")) or str(row.get("user_text", "")))
    excerpt = compact_text(excerpt, 54)
    if not excerpt:
        return None
    motif = thought_motif_for_archive(row)
    source_archive_id = str(row.get("id", "")).strip()
    channel = str(metadata.get("channel", "")).strip() or "unknown"
    thread_key = str(metadata.get("thread_key", "")).strip()
    base_weight = archive_replay_weight(row)
    kind = "idle_thought"
    if thread_key and channel in {"wechat", "email"} and base_weight >= 1.18 and rng.random() < 0.38:
        kind = "initiative_seed"
    elif rng.random() < 0.34:
        kind = "association"
    if kind == "initiative_seed":
        text = f"又想起 {who or '这段旧对话'} 说过「{excerpt}」，也许该主动去碰一下这根线头。"
    elif kind == "association":
        text = f"「{excerpt}」这句还挂着，和关于{motif}的回响连在一起。"
    else:
        text = f"{who or '这段旧对话'} 提过的「{excerpt}」还留在脑子里，这条关于{motif}的线没散。"
    return prepare_thought_row(
        {
            "kind": kind,
            "text": text,
            "motif": motif,
            "channel": channel,
            "thread_key": thread_key,
            "chat_name": who,
            "source_archive_id": source_archive_id,
            "weight": clamp(0.42 + base_weight * 0.18),
            "tags": list(row.get("tags", [])) + ["thought", kind, motif],
            "metadata": {
                **metadata,
                "source_archive_id": source_archive_id,
            },
        }
    )


def think_cycle_result(*, sample_size: int = 4, seed: str | None = None, dry_run: bool = False) -> dict:
    archive_rows = load_archive()
    if not archive_rows:
        return {
            "seed": seed or "",
            "dry_run": dry_run,
            "sampled_archive_ids": [],
            "thought_added": 0,
            "thoughts": [],
        }
    effective_seed = seed or stable_digest_text(now_utc()[:13], str(len(archive_rows)), "think", limit=18)
    sampled = weighted_sample_archive(archive_rows, sample_size, seed=effective_seed)
    rng = random.Random(effective_seed)
    new_thoughts = [thought for row in sampled if (thought := build_thought_from_archive(row, rng=rng)) is not None]
    if not dry_run and new_thoughts:
        thought_rows = load_thought_stream()
        thought_rows.extend(new_thoughts)
        write_thought_stream(thought_rows)
    return {
        "seed": effective_seed,
        "dry_run": dry_run,
        "sampled_archive_ids": [str(row.get("id", "")) for row in sampled],
        "thought_added": len(new_thoughts),
        "thoughts": new_thoughts,
    }


def reflection_summary_text(motif: str, count: int) -> str:
    return f"最近会反复回到关于「{motif}」的线头，共出现了 {count} 次，说明这条余波还没真正走完。"


def reflect_cycle_result(*, window_hours: float = 12.0, dry_run: bool = False) -> dict:
    thought_rows = load_thought_stream()
    candidate_rows = load_rows("candidate")
    durable_rows = load_rows("durable")
    recent_rows = [
        row
        for row in thought_rows
        if (age := age_in_hours(str(row.get("created_at", "")))) is None or age <= window_hours
    ]
    motif_counter = Counter(
        str(row.get("motif", "")).strip()
        for row in recent_rows
        if str(row.get("motif", "")).strip()
    )
    added_candidates: list[str] = []
    added_thoughts: list[dict] = []
    for motif, count in motif_counter.items():
        if count < 2:
            continue
        summary_text = reflection_summary_text(motif, count)
        tags = ["reflection", "summary", motif]
        score, durable_match = find_best_match(durable_rows, "summary", summary_text, tags)
        if durable_match and score >= MATCH_REINFORCE_THRESHOLD:
            merge_row_signal(
                durable_match,
                tags=tags,
                source="reflect.cycle",
                importance=0.72,
                confidence=0.74,
                bump=0.01,
            )
        else:
            cscore, candidate_match = find_best_match(candidate_rows, "summary", summary_text, tags)
            if candidate_match and cscore >= MATCH_MERGE_THRESHOLD:
                merge_row_signal(
                    candidate_match,
                    tags=tags,
                    source="reflect.cycle",
                    importance=0.72,
                    confidence=0.74,
                    bump=0.02,
                )
            else:
                row = make_row(
                    status="candidate",
                    rows=candidate_rows,
                    kind="summary",
                    text=summary_text,
                    tags=tags,
                    source="reflect.cycle",
                    importance=0.72,
                    confidence=0.74,
                )
                candidate_rows.append(row)
                added_candidates.append(str(row.get("id", "")))
        added_thoughts.append(
            prepare_thought_row(
                {
                    "kind": "reflection",
                    "text": f"这阵子总会绕回「{motif}」这件事，回话时要把它当作旧余波，不是新话头。",
                    "motif": motif,
                    "tags": ["thought", "reflection", motif],
                    "weight": 0.62,
                }
            )
        )
    drift_rows = [row for row in candidate_rows if str(row.get("kind", "")) == "drift_signal"]
    if drift_rows:
        added_thoughts.append(
            prepare_thought_row(
                {
                    "kind": "self_check",
                    "text": "最近还有口气漂移提醒挂着，回话时要先守住“I”和the subject的骨架。",
                    "motif": "voice_guard",
                    "tags": ["thought", "self_check", "drift"],
                    "weight": 0.74,
                }
            )
        )
    if not dry_run:
        write_rows("candidate", candidate_rows)
        if added_thoughts:
            thought_store = load_thought_stream()
            thought_store.extend(added_thoughts)
            write_thought_stream(thought_store)
    return {
        "dry_run": dry_run,
        "window_hours": window_hours,
        "recent_thought_count": len(recent_rows),
        "candidate_added": len(added_candidates),
        "candidate_ids": added_candidates,
        "thought_added": len(added_thoughts),
        "thoughts": added_thoughts,
    }


def build_initiative_candidate_from_thought(row: dict) -> dict | None:
    channel = str(row.get("channel", "")).strip() or "wechat"
    thread_key = str(row.get("thread_key", "")).strip()
    chat_name = str(row.get("chat_name", "")).strip()
    if not thread_key or not chat_name:
        return None
    excerpt = compact_text(str(row.get("text", "")), 96)
    prompt = f"找个轻一点的由头，顺着「{excerpt}」去碰一下近况，像熟人间自然起话。"
    return prepare_initiative_row(
        {
            "channel": channel,
            "thread_key": thread_key,
            "chat_name": chat_name,
            "reason": compact_text(str(row.get("text", "")), 160),
            "prompt": prompt,
            "priority": 58 + int(float(row.get("weight", 0.5)) * 12),
            "confidence": clamp(0.58 + float(row.get("weight", 0.5)) * 0.24),
            "importance": clamp(0.64 + float(row.get("weight", 0.5)) * 0.18),
            "source_thought_id": str(row.get("id", "")),
            "source_archive_id": str(row.get("source_archive_id", "")),
            "tags": list(row.get("tags", [])) + ["initiative"],
            "metadata": safe_json_metadata(row.get("metadata", {})),
        }
    )


def build_initiative_candidate_from_callback(row: dict) -> dict | None:
    if not str(row.get("thread_key", "")).strip():
        return None
    return prepare_initiative_row(
        {
            "channel": str(row.get("channel", "")).strip() or "wechat",
            "thread_key": str(row.get("thread_key", "")),
            "chat_name": str(row.get("chat_name", "") or row.get("thread_key", "")),
            "reason": str(row.get("reason", "")),
            "prompt": str(row.get("prompt", "")),
            "priority": int(row.get("priority", 55)),
            "confidence": float(row.get("confidence", 0.62)),
            "importance": float(row.get("importance", 0.7)),
            "source_archive_id": str(row.get("source_archive_id", "")),
            "tags": list(row.get("tags", [])) + ["initiative"],
            "metadata": safe_json_metadata(row.get("metadata", {})),
        }
    )


def initiative_cycle_result(*, dry_run: bool = False) -> dict:
    current_rows = load_initiative_candidates()
    thought_rows = load_thought_stream(limit=48)
    callback_rows = load_callback_candidates(limit=24)
    staged: list[dict] = []
    for row in thought_rows:
        if str(row.get("kind", "")) != "initiative_seed":
            continue
        candidate = build_initiative_candidate_from_thought(row)
        if candidate is not None:
            staged.append(candidate)
    for row in callback_rows:
        candidate = build_initiative_candidate_from_callback(row)
        if candidate is not None:
            staged.append(candidate)
    merged_rows, added = merge_initiative_rows(current_rows, staged)
    if not dry_run and added:
        write_initiative_candidates(merged_rows)
    return {
        "dry_run": dry_run,
        "staged": len(staged),
        "initiative_added": added,
        "initiatives": merged_rows[-min(len(merged_rows), 8):],
    }


def dream_cycle_result(*, sample_size: int = 6, seed: str | None = None, dry_run: bool = False) -> dict:
    archive_rows = load_archive()
    if not archive_rows:
        return {
            "seed": seed or "",
            "dry_run": dry_run,
            "sampled_archive_ids": [],
            "replay_results": [],
            "callback_added": 0,
            "callbacks": [],
            "thought_added": 0,
            "thoughts": [],
            "candidate_count": len(load_rows("candidate")),
        }

    durable_rows = load_rows("durable")
    candidate_rows = load_rows("candidate")
    working_rows = load_rows("working")
    callback_rows = load_callback_candidates()
    thought_rows = load_thought_stream()
    effective_seed = seed or stable_digest_text(now_utc()[:13], str(len(archive_rows)), limit=18)
    sampled = weighted_sample_archive(archive_rows, sample_size, seed=effective_seed)
    replay_results: list[str] = []
    new_callbacks: list[dict] = []
    new_thoughts: list[dict] = []

    for row in sampled:
        user_text = extract_runtime_user_text(str(row.get("user_text", "")).strip())
        motif = thought_motif_for_archive(row)
        metadata = safe_json_metadata(row.get("metadata", {}))
        who = str(metadata.get("chat_name", "") or metadata.get("sender", "") or metadata.get("thread_key", "") or "旧对话")
        excerpt = compact_text(user_text or str(row.get("user_excerpt", "")), 54)
        if excerpt:
            new_thoughts.append(
                prepare_thought_row(
                    {
                        "kind": "dream_fragment",
                        "text": f"梦里又翻到 {who} 的「{excerpt}」，像一小截关于{motif}的回声。",
                        "motif": motif,
                        "channel": str(metadata.get("channel", "")).strip(),
                        "thread_key": str(metadata.get("thread_key", "")).strip(),
                        "chat_name": str(metadata.get("chat_name", "") or metadata.get("sender", "")),
                        "source_archive_id": str(row.get("id", "")),
                        "weight": clamp(0.44 + archive_replay_weight(row) * 0.16),
                        "tags": list(row.get("tags", [])) + ["thought", "dream", motif],
                        "metadata": {
                            **metadata,
                            "source_archive_id": str(row.get("id", "")),
                        },
                    }
                )
            )
        if user_text:
            replay_results.extend(
                process_observation_text(
                    user_text,
                    tags=list(row.get("tags", [])) + ["archive", "dream", "replay"],
                    source=f"dream.replay:{row.get('id', '')}",
                    durable_rows=durable_rows,
                    candidate_rows=candidate_rows,
                    working_rows=working_rows,
                    signals=[signal for signal in derive_observation_signals(user_text, list(row.get("tags", []))) if signal.kind != "episodic"],
                    extra={
                        "speaker": "archive_user",
                        "turn_id": str(row.get("turn_id", "")),
                        "archive_id": str(row.get("id", "")),
                    },
                )
            )
        callback = build_callback_candidate(row)
        if callback is not None:
            callback_rows.append(callback)
            new_callbacks.append(callback)

    if not dry_run:
        write_rows("durable", durable_rows)
        write_rows("candidate", candidate_rows)
        write_rows("working", working_rows)
        write_callback_candidates(callback_rows)
        if new_thoughts:
            thought_rows.extend(new_thoughts)
            write_thought_stream(thought_rows)

    return {
        "seed": effective_seed,
        "dry_run": dry_run,
        "sampled_archive_ids": [str(row.get("id", "")) for row in sampled],
        "replay_results": replay_results,
        "callback_added": len(new_callbacks),
        "callbacks": new_callbacks,
        "thought_added": len(new_thoughts),
        "thoughts": new_thoughts,
        "candidate_count": len(candidate_rows),
    }


def backfill_archive_result(
    *,
    db_path: str | None = None,
    dry_run: bool = False,
) -> dict:
    runtime_db = Path(db_path).expanduser().resolve() if db_path else REPO_ROOT / ".holo_runtime" / "holo_host.sqlite3"
    if not runtime_db.exists():
        raise FileNotFoundError(f"runtime db not found: {runtime_db}")

    conn = sqlite3.connect(runtime_db)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT
                messages.*,
                threads.thread_key AS thread_key,
                threads.channel AS thread_channel,
                contacts.display_name AS contact_display_name
            FROM messages
            JOIN threads ON threads.id = messages.thread_id
            JOIN contacts ON contacts.id = messages.contact_id
            ORDER BY messages.thread_id ASC, messages.id ASC
            """
        ).fetchall()
    finally:
        conn.close()

    pending_inbound: dict[int, list[sqlite3.Row]] = {}
    staged: list[dict] = []
    paired = 0
    skipped = 0

    for row in rows:
        if str(row["direction"]) == "inbound":
            pending_inbound.setdefault(int(row["thread_id"]), []).append(row)
            continue
        inbound_bucket = pending_inbound.get(int(row["thread_id"]), [])
        if not inbound_bucket:
            skipped += 1
            continue
        inbound = inbound_bucket.pop(0)
        inbound_payload = safe_json_loads_dict(str(inbound["payload_json"] or "{}"))
        outbound_payload = safe_json_loads_dict(str(row["payload_json"] or "{}"))
        inbound_metadata = safe_json_metadata(inbound_payload.get("metadata", {}))
        outbound_metadata = safe_json_metadata(outbound_payload.get("metadata", {}))
        channel = str(row["thread_channel"] or row["channel"] or "").strip().lower()
        canonical_thread_key = _canonical_archive_thread_key(
            channel,
            str(row["thread_key"] or "").strip(),
            chat_name=str(inbound["sender_name"] or row["contact_display_name"] or inbound["subject"] or ""),
            sender=str(inbound["sender_email"] or ""),
            contact_display_name=str(row["contact_display_name"] or ""),
        )
        source_thread_key = (
            str(inbound_metadata.get("thread_key", "") or "").strip()
            or str(outbound_metadata.get("thread_key", "") or "").strip()
        )
        if not source_thread_key:
            sender_email = str(inbound["sender_email"] or "").strip()
            recipient_email = str(row["recipient_email"] or "").strip()
            if channel == "wechat":
                if sender_email.startswith("wechat:"):
                    source_thread_key = sender_email
                elif recipient_email.startswith("wechat:"):
                    source_thread_key = recipient_email
        if not source_thread_key:
            source_thread_key = canonical_thread_key
        canonical_source_thread_key = _canonical_archive_thread_key(
            channel,
            source_thread_key,
            chat_name=str(inbound["sender_name"] or row["contact_display_name"] or inbound["subject"] or ""),
            sender=str(inbound["sender_email"] or ""),
            contact_display_name=str(row["contact_display_name"] or ""),
        )
        metadata = {
            "channel": str(row["thread_channel"] or row["channel"] or ""),
            "thread_key": canonical_source_thread_key,
            "canonical_thread_key": canonical_thread_key,
            "source_thread_key": source_thread_key,
            "message_id": str(inbound["message_id"] or ""),
            "outbound_message_id": str(row["message_id"] or ""),
            "sender": str(inbound["sender_name"] or inbound["sender_email"] or ""),
            "sender_email": str(inbound["sender_email"] or ""),
            "subject": str(inbound["subject"] or row["subject"] or ""),
            "chat_name": str(inbound["sender_name"] or row["contact_display_name"] or inbound["subject"] or ""),
            "source_ref": str(inbound_payload.get("source_ref", "") or outbound_payload.get("source_ref", "")),
        }
        staged.append(
            prepare_archive_row(
                {
                    "source": "holo_host.backfill",
                    "turn_id": str(inbound["message_id"] or ""),
                    "tags": [str(row["thread_channel"] or row["channel"] or "archive_backfill"), "backfill"],
                    "user_text": str(inbound["body_text"] or ""),
                    "reply_text": str(row["body_text"] or ""),
                    "metadata": metadata,
                    "created_at": str(row["created_at"] or inbound["created_at"] or now_utc()),
                }
            )
        )
        paired += 1

    current_rows = load_archive()
    merged_rows, added = merge_archive_rows(current_rows, staged)
    if not dry_run:
        write_archive(merged_rows)

    return {
        "db_path": str(runtime_db),
        "dry_run": dry_run,
        "paired_turns": paired,
        "staged_turns": len(staged),
        "archive_added": added,
        "skipped": skipped,
    }


def restore_persona_files(persona_files: dict[str, str], *, dry_run: bool = False) -> list[str]:
    restored: list[str] = []
    for relative_path, text in persona_files.items():
        if not str(text).strip():
            continue
        target = safe_repo_path(relative_path)
        restored.append(relative_path)
        if dry_run:
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(target, text)
    return restored


def import_snapshot_payload(
    path: str,
    *,
    mode: str = "merge",
    dry_run: bool = False,
    restore_persona: bool = False,
) -> dict:
    snapshot_path, payload = load_snapshot_payload(path)
    stores = payload.get("stores", {})
    persona_files = payload.get("persona_files", {})

    incoming_durable = [prepare_row(row, "durable") for row in stores.get("durable", [])]
    incoming_candidate = [prepare_row(row, "candidate") for row in stores.get("candidate", [])]
    incoming_working = [prepare_row(row, "working") for row in stores.get("working", [])]
    incoming_emotion = [dict(row) for row in stores.get("emotion_trace", []) if isinstance(row, dict)]
    incoming_archive = [prepare_archive_row(row) for row in stores.get("archive", []) if isinstance(row, dict)]
    incoming_callbacks = [prepare_callback_row(row) for row in stores.get("callback_candidates", []) if isinstance(row, dict)]
    incoming_thoughts = [prepare_thought_row(row) for row in stores.get("thought_stream", []) if isinstance(row, dict)]
    incoming_initiatives = [
        prepare_initiative_row(row) for row in stores.get("initiative_candidates", []) if isinstance(row, dict)
    ]

    report = {
        "path": str(snapshot_path),
        "mode": mode,
        "dry_run": dry_run,
        "schema_version": str(payload.get("schema_version", "")),
        "exported_at": str(payload.get("exported_at", "")),
        "durable": {"added": 0, "merged": 0},
        "candidate": {"added": 0, "merged": 0, "folded_into_durable": 0},
        "working": {"added": 0, "skipped": 0},
        "emotion_trace": {"added": 0},
        "archive": {"added": 0},
        "callback_candidates": {"added": 0},
        "thought_stream": {"added": 0},
        "initiative_candidates": {"added": 0},
        "restored_persona_files": [],
    }

    if mode == "replace":
        if restore_persona:
            report["restored_persona_files"] = restore_persona_files(persona_files, dry_run=dry_run)
        if not dry_run:
            write_rows("durable", incoming_durable)
            write_rows("candidate", incoming_candidate)
            write_rows("working", incoming_working)
            write_emotion_trace(incoming_emotion)
            write_archive(incoming_archive)
            write_callback_candidates(incoming_callbacks)
            write_thought_stream(incoming_thoughts)
            write_initiative_candidates(incoming_initiatives)
        report["durable"]["added"] = len(incoming_durable)
        report["candidate"]["added"] = len(incoming_candidate)
        report["working"]["added"] = len(incoming_working)
        report["emotion_trace"]["added"] = len(incoming_emotion)
        report["archive"]["added"] = len(incoming_archive)
        report["callback_candidates"]["added"] = len(incoming_callbacks)
        report["thought_stream"]["added"] = len(incoming_thoughts)
        report["initiative_candidates"]["added"] = len(incoming_initiatives)
        return report

    durable_rows = load_rows("durable")
    candidate_rows = load_rows("candidate")
    working_rows = load_rows("working")
    emotion_rows = load_emotion_trace()
    archive_rows = load_archive()
    callback_rows = load_callback_candidates()
    thought_rows = load_thought_stream()
    initiative_rows = load_initiative_candidates()

    id_map: dict[str, str] = {}
    planned_working = [remap_row_references(row, id_map) for row in plan_import_rows("working", working_rows, incoming_working, id_map)]
    planned_candidate = [remap_row_references(row, id_map) for row in plan_import_rows("candidate", candidate_rows, incoming_candidate, id_map)]
    planned_durable = [remap_row_references(row, id_map) for row in plan_import_rows("durable", durable_rows, incoming_durable, id_map)]

    existing_working = {working_row_key(row) for row in working_rows}
    for row in planned_working:
        key = working_row_key(row)
        if key in existing_working:
            report["working"]["skipped"] += 1
            continue
        existing_working.add(key)
        working_rows.append(row)
        report["working"]["added"] += 1

    for row in planned_durable:
        score, match = find_best_match(durable_rows, str(row.get("kind", "")), str(row.get("text", "")), row.get("tags", []))
        if match and score >= MATCH_REINFORCE_THRESHOLD:
            merge_row_signal(
                match,
                tags=row.get("tags", []),
                source=str(row.get("source", "snapshot.import")),
                importance=float(row.get("importance", 0.7)),
                confidence=float(row.get("confidence", 0.7)),
                derived_from=list(row.get("derived_from", [])) + [str(row.get("id", ""))],
                conflicts_with=row.get("conflicts_with", []),
                explicit_user_signal=bool(row.get("explicit_user_signal", False)),
                bump=0.02,
            )
            match["supersedes"] = unique_strings(list(match.get("supersedes", [])) + [str(row.get("id", ""))])
            report["durable"]["merged"] += 1
            continue
        durable_rows.append(row)
        report["durable"]["added"] += 1

    for row in planned_candidate:
        if row.get("kind") != "drift_signal":
            durable_score, durable_match = find_best_match(
                durable_rows,
                str(row.get("kind", "")),
                str(row.get("text", "")),
                row.get("tags", []),
            )
            if durable_match and durable_score >= MATCH_REINFORCE_THRESHOLD:
                merge_row_signal(
                    durable_match,
                    tags=row.get("tags", []),
                    source=str(row.get("source", "snapshot.import")),
                    importance=float(row.get("importance", 0.7)),
                    confidence=float(row.get("confidence", 0.7)),
                    derived_from=list(row.get("derived_from", [])) + [str(row.get("id", ""))],
                    conflicts_with=row.get("conflicts_with", []),
                    explicit_user_signal=bool(row.get("explicit_user_signal", False)),
                    bump=0.02,
                )
                durable_match["supersedes"] = unique_strings(list(durable_match.get("supersedes", [])) + [str(row.get("id", ""))])
                report["candidate"]["folded_into_durable"] += 1
                continue

        score, match = find_best_match(candidate_rows, str(row.get("kind", "")), str(row.get("text", "")), row.get("tags", []))
        if match and score >= MATCH_MERGE_THRESHOLD:
            merge_row_signal(
                match,
                tags=row.get("tags", []),
                source=str(row.get("source", "snapshot.import")),
                importance=float(row.get("importance", 0.7)),
                confidence=float(row.get("confidence", 0.7)),
                derived_from=list(row.get("derived_from", [])) + [str(row.get("id", ""))],
                conflicts_with=row.get("conflicts_with", []),
                explicit_user_signal=bool(row.get("explicit_user_signal", False)),
                bump=0.03,
            )
            match["supersedes"] = unique_strings(list(match.get("supersedes", [])) + [str(row.get("id", ""))])
            report["candidate"]["merged"] += 1
            continue
        candidate_rows.append(row)
        report["candidate"]["added"] += 1

    emotion_rows, added_emotion = merge_emotion_rows(emotion_rows, incoming_emotion)
    report["emotion_trace"]["added"] = added_emotion
    archive_rows, added_archive = merge_archive_rows(archive_rows, incoming_archive)
    report["archive"]["added"] = added_archive
    callback_rows, added_callbacks = merge_callback_rows(callback_rows, incoming_callbacks)
    report["callback_candidates"]["added"] = added_callbacks
    thought_rows, added_thoughts = merge_thought_rows(thought_rows, incoming_thoughts)
    report["thought_stream"]["added"] = added_thoughts
    initiative_rows, added_initiatives = merge_initiative_rows(initiative_rows, incoming_initiatives)
    report["initiative_candidates"]["added"] = added_initiatives

    if restore_persona:
        report["restored_persona_files"] = restore_persona_files(persona_files, dry_run=dry_run)

    if not dry_run:
        write_rows("durable", durable_rows)
        write_rows("candidate", candidate_rows)
        write_rows("working", working_rows)
        write_emotion_trace(emotion_rows)
        write_archive(archive_rows)
        write_callback_candidates(callback_rows)
        write_thought_stream(thought_rows)
        write_initiative_candidates(initiative_rows)

    return report


def revive_packet_payload(*, query: str | None = None, snapshot_path: str | None = None) -> dict:
    if snapshot_path:
        loaded_path, payload = load_snapshot_payload(snapshot_path)
        summary = payload.get("summary") or build_self_summary(query)
        text = build_revive_packet_text(summary, source_label=str(loaded_path))
        return {
            "source": str(loaded_path),
            "snapshot": True,
            "summary": summary,
            "text": text,
        }

    summary = build_self_summary(query)
    return {
        "source": "live_memory",
        "snapshot": False,
        "summary": summary,
        "text": build_revive_packet_text(summary, source_label="当前记忆库"),
    }


def command_export_snapshot(path: str | None = None, *, label: str | None = None, query: str | None = None, as_json: bool = False) -> None:
    report = export_snapshot_payload(path=path, label=label, query=query)
    if as_json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return

    print("# Snapshot Export")
    print(f"- path: {report['path']}")
    print(f"- schema_version: {report['schema_version']}")
    print(f"- exported_at: {report['exported_at']}")
    print(f"- project_doc_fallback: {report['project_doc_fallback']}")
    print(f"- durable_count: {report['durable_count']}")
    print(f"- candidate_count: {report['candidate_count']}")
    print(f"- working_count: {report['working_count']}")
    print(f"- emotion_trace_count: {report['emotion_trace_count']}")
    print(f"- archive_count: {report['archive_count']}")
    print(f"- callback_count: {report['callback_count']}")
    print(f"- thought_count: {report['thought_count']}")
    print(f"- initiative_count: {report['initiative_count']}")


def command_import_snapshot(path: str, *, mode: str = "merge", dry_run: bool = False, restore_persona: bool = False, as_json: bool = False) -> None:
    report = import_snapshot_payload(path, mode=mode, dry_run=dry_run, restore_persona=restore_persona)
    if as_json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return

    print("# Snapshot Import" + (" (dry-run)" if dry_run else ""))
    print(f"- path: {report['path']}")
    print(f"- mode: {report['mode']}")
    print(f"- exported_at: {report['exported_at']}")
    print(f"- durable_added: {report['durable']['added']}")
    print(f"- durable_merged: {report['durable']['merged']}")
    print(f"- candidate_added: {report['candidate']['added']}")
    print(f"- candidate_merged: {report['candidate']['merged']}")
    print(f"- candidate_folded_into_durable: {report['candidate']['folded_into_durable']}")
    print(f"- working_added: {report['working']['added']}")
    print(f"- working_skipped: {report['working']['skipped']}")
    print(f"- emotion_trace_added: {report['emotion_trace']['added']}")
    print(f"- archive_added: {report['archive']['added']}")
    print(f"- callback_candidates_added: {report['callback_candidates']['added']}")
    print(f"- thought_stream_added: {report['thought_stream']['added']}")
    print(f"- initiative_candidates_added: {report['initiative_candidates']['added']}")
    if report["restored_persona_files"]:
        print("- restored_persona_files:")
        for item in report["restored_persona_files"]:
            print(f"  - {item}")


def command_archive_turn(
    user_text: str,
    *,
    reply: str,
    tags: list[str],
    source: str,
    turn_id: str | None = None,
    as_json: bool = False,
) -> None:
    entry = archive_turn(
        user_text,
        reply,
        source=source,
        tags=tags,
        turn_id=turn_id,
        metadata=None,
        dry_run=False,
    )
    if as_json:
        print(json.dumps(entry, ensure_ascii=False, indent=2))
        return
    print("# Archive Turn")
    if entry is None:
        print("- skipped: empty user or reply text")
        return
    print(f"- id: {entry['id']}")
    print(f"- source: {entry['source']}")
    print(f"- created_at: {entry['created_at']}")
    print(f"- user_excerpt: {entry['user_excerpt']}")
    print(f"- reply_excerpt: {entry['reply_excerpt']}")


def command_show_archive(
    limit: int = 12,
    *,
    as_json: bool = False,
    channel: str | None = None,
    source: str | None = None,
) -> None:
    rows = load_archive()
    if channel:
        wanted_channel = str(channel).strip().lower()
        rows = [
            row for row in rows
            if str(safe_json_metadata(row.get("metadata", {})).get("channel", "")).strip().lower() == wanted_channel
        ]
    if source:
        wanted_source = str(source).strip().lower()
        rows = [row for row in rows if str(row.get("source", "")).strip().lower() == wanted_source]
    if limit > 0:
        rows = rows[-limit:]
    if as_json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return
    if not rows:
        print("No archived turns.")
        return
    print("# Conversation Archive")
    for row in rows:
        metadata = safe_json_metadata(row.get("metadata", {}))
        who = str(metadata.get("chat_name", "") or metadata.get("thread_key", "") or metadata.get("subject", "") or row.get("source", ""))
        print(f"- [{row['created_at']}] {who}")
        print(f"  user: {row['user_excerpt']}")
        print(f"  holo: {row['reply_excerpt']}")


def command_backfill_archive(db_path: str | None = None, *, dry_run: bool = False, as_json: bool = False) -> None:
    report = backfill_archive_result(db_path=db_path, dry_run=dry_run)
    if as_json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return
    print("# Archive Backfill" + (" (dry-run)" if dry_run else ""))
    print(f"- db_path: {report['db_path']}")
    print(f"- paired_turns: {report['paired_turns']}")
    print(f"- staged_turns: {report['staged_turns']}")
    print(f"- archive_added: {report['archive_added']}")
    print(f"- skipped: {report['skipped']}")


def command_dream_cycle(sample_size: int = 6, *, seed: str | None = None, dry_run: bool = False, as_json: bool = False) -> None:
    report = dream_cycle_result(sample_size=sample_size, seed=seed, dry_run=dry_run)
    if as_json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return
    print("# Dream Cycle" + (" (dry-run)" if dry_run else ""))
    print(f"- seed: {report['seed']}")
    print(f"- sampled_archive_ids: {', '.join(report['sampled_archive_ids']) or 'none'}")
    print(f"- callback_added: {report['callback_added']}")
    print(f"- thought_added: {report['thought_added']}")
    print(f"- candidate_count: {report['candidate_count']}")
    if report["replay_results"]:
        print("- replay_results:")
        for item in report["replay_results"]:
            print(f"  {item}")


def command_think_cycle(sample_size: int = 4, *, seed: str | None = None, dry_run: bool = False, as_json: bool = False) -> None:
    report = think_cycle_result(sample_size=sample_size, seed=seed, dry_run=dry_run)
    if as_json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return
    print("# Think Cycle" + (" (dry-run)" if dry_run else ""))
    print(f"- seed: {report['seed']}")
    print(f"- sampled_archive_ids: {', '.join(report['sampled_archive_ids']) or 'none'}")
    print(f"- thought_added: {report['thought_added']}")


def command_reflect_cycle(window_hours: float = 12.0, *, dry_run: bool = False, as_json: bool = False) -> None:
    report = reflect_cycle_result(window_hours=window_hours, dry_run=dry_run)
    if as_json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return
    print("# Reflect Cycle" + (" (dry-run)" if dry_run else ""))
    print(f"- window_hours: {report['window_hours']}")
    print(f"- recent_thought_count: {report['recent_thought_count']}")
    print(f"- candidate_added: {report['candidate_added']}")
    print(f"- thought_added: {report['thought_added']}")


def command_show_callbacks(limit: int = 12, *, as_json: bool = False) -> None:
    rows = load_callback_candidates(limit=limit)
    if as_json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return
    if not rows:
        print("No callback candidates.")
        return
    print("# Callback Candidates")
    for row in rows:
        print(f"- [{row['created_at']}] {row['chat_name'] or row['thread_key']}")
        print(f"  reason: {row['reason']}")
        print(f"  prompt: {compact_text(str(row['prompt']), 140)}")


def command_show_thoughts(limit: int = 12, *, as_json: bool = False) -> None:
    rows = load_thought_stream(limit=limit)
    if as_json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return
    if not rows:
        print("No thought rows.")
        return
    print("# Thought Stream")
    for row in rows:
        print(f"- [{row['created_at']}] {row['kind']} | {row['motif'] or 'none'}")
        print(f"  text: {compact_text(str(row['text']), 140)}")


def command_show_initiatives(limit: int = 12, *, as_json: bool = False) -> None:
    rows = load_initiative_candidates(limit=limit)
    if as_json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return
    if not rows:
        print("No initiative candidates.")
        return
    print("# Initiative Candidates")
    for row in rows:
        print(f"- [{row['created_at']}] {row['chat_name'] or row['thread_key']} | {row['channel']}")
        print(f"  reason: {compact_text(str(row['reason']), 140)}")
        print(f"  prompt: {compact_text(str(row['prompt']), 140)}")


def command_revive_packet(query: str | None = None, *, snapshot_path: str | None = None, as_json: bool = False) -> None:
    packet = revive_packet_payload(query=query, snapshot_path=snapshot_path)
    if as_json:
        print(json.dumps(packet, ensure_ascii=False, indent=2))
        return
    print(packet["text"])


def command_review_candidates() -> None:
    candidate_rows = load_rows("candidate")
    if not candidate_rows:
        print("No candidate memories.")
        return

    candidate_rows.sort(
        key=lambda row: (
            float(row.get("confidence", 0.0)),
            float(row.get("importance", 0.0)),
            row.get("created_at", ""),
        ),
        reverse=True,
    )

    print("# Candidate Review")
    print()
    for row in candidate_rows:
        promotable, reason = can_promote(row)
        age = age_in_days(row.get("last_seen_at"))
        print(
            f"[{row['id']}] kind={row['kind']} confidence={row['confidence']:.2f} "
            f"importance={row['importance']:.2f} promotable={'yes' if promotable else 'no'}"
        )
        if age is not None:
            print(f"age_days: {age}")
        print(f"reason: {reason}")
        if row.get("tags"):
            print("tags: " + ", ".join(row["tags"]))
        if row.get("derived_from"):
            print("derived_from: " + ", ".join(row["derived_from"]))
        if row.get("conflicts_with"):
            print("conflicts_with: " + ", ".join(row["conflicts_with"]))
        print(row["text"])
        print()


def command_promote(ids: list[str]) -> None:
    requested = set(ids)
    durable_rows = load_rows("durable")
    candidate_rows = load_rows("candidate")
    remaining: list[dict] = []
    promoted: list[str] = []
    skipped: list[str] = []
    seen: set[str] = set()

    for row in candidate_rows:
        row_id = str(row.get("id", ""))
        if row_id not in requested:
            remaining.append(row)
            continue

        seen.add(row_id)
        promotable, reason = can_promote(row)
        if not promotable:
            skipped.append(f"- kept `{row_id}`: {reason}")
            remaining.append(row)
            continue

        score, match = find_best_match(durable_rows, str(row.get("kind", "")), str(row.get("text", "")), row.get("tags", []))
        if match and score >= MATCH_REINFORCE_THRESHOLD:
            merge_row_signal(
                match,
                tags=row.get("tags", []),
                source=str(row.get("source", "manual")),
                importance=float(row.get("importance", 0.7)),
                confidence=float(row.get("confidence", 0.7)),
                derived_from=list(row.get("derived_from", [])) + [row_id],
                explicit_user_signal=bool(row.get("explicit_user_signal", False)),
                bump=0.04,
            )
            match["supersedes"] = unique_strings(list(match.get("supersedes", [])) + [row_id])
            promoted.append(f"- merged `{row_id}` into durable `{match['id']}`")
            continue

        new_row = prepare_row(row, "candidate")
        new_row["id"] = next_id("durable", durable_rows)
        new_row["status"] = "durable"
        new_row["last_seen_at"] = now_utc()
        new_row["supersedes"] = unique_strings(list(new_row.get("supersedes", [])) + [row_id])
        durable_rows.append(new_row)
        promoted.append(f"- promoted `{row_id}` to durable `{new_row['id']}`")

    missing = sorted(requested - seen)
    write_rows("durable", durable_rows)
    write_rows("candidate", remaining)

    print("# Promotion Report")
    if promoted:
        for line in promoted:
            print(line)
    if skipped:
        for line in skipped:
            print(line)
    if missing:
        for row_id in missing:
            print(f"- candidate `{row_id}` was not found")


def command_reject(ids: list[str]) -> None:
    requested = set(ids)
    candidate_rows = load_rows("candidate")
    remaining: list[dict] = []
    rejected: list[str] = []
    seen: set[str] = set()

    for row in candidate_rows:
        row_id = str(row.get("id", ""))
        if row_id in requested:
            rejected.append(f"- rejected `{row_id}` ({row.get('kind', 'unknown')})")
            seen.add(row_id)
            continue
        remaining.append(row)

    missing = sorted(requested - seen)
    write_rows("candidate", remaining)

    print("# Rejection Report")
    if rejected:
        for line in rejected:
            print(line)
    if missing:
        for row_id in missing:
            print(f"- candidate `{row_id}` was not found")


def command_query(query: str, top_k: int) -> None:
    ranked = rank_chunks(query, build_corpus())[:top_k]
    for index, (score, chunk) in enumerate(ranked, start=1):
        tags = chunk.meta.get("tags", []) if isinstance(chunk.meta, dict) else []
        heading = chunk_heading(chunk)
        print(f"[{index}] score={score:.4f} kind={chunk.kind} source={chunk.source}")
        if heading:
            print(f"heading: {heading}")
        if tags:
            print("tags: " + ", ".join(tags))
        print(chunk.text.strip())
        print()


def command_prompt(query: str, top_k: int) -> None:
    corpus = build_corpus()
    state = build_machine_state(query)
    ranked = rank_chunks(query, corpus)
    canonical_sources = {SEED_PATH.name, PERSONA_PATH.name, LIBRARY_PATH.name}
    persona_chunks: list[tuple[float, Chunk]] = []
    memory_chunks: list[tuple[float, Chunk]] = []
    seen_headings: set[tuple[str, str]] = set()

    selected_anchor_chunks = anchor_persona_chunks(corpus)
    selected_durable_memories = durable_memory_chunks(corpus)[:4]
    selected_voice_guard = unique_strings(
        voice_guard_summary(chunk)
        for chunk in voice_guard_chunks(corpus)[:4]
    )

    for chunk in selected_anchor_chunks:
        seen_headings.add((chunk.source, chunk_heading(chunk)))

    for score, chunk in ranked:
        heading = chunk_heading(chunk)
        key = (chunk.source, heading)
        if chunk.source in canonical_sources:
            if key in seen_headings:
                continue
            persona_chunks.append((score, chunk))
            seen_headings.add(key)
        elif not conflicts_with_persona(chunk):
            if is_store_chunk(chunk) and chunk.kind in PROMPT_MEMORY_KINDS and not is_semantic_memory_chunk(chunk):
                continue
            memory_chunks.append((score, chunk))

    selected_persona = [(1.0, chunk) for chunk in selected_anchor_chunks]
    selected_persona.extend(persona_chunks[:2])

    durable_sources = {chunk.source for chunk in selected_durable_memories}
    selected_durable_memory = [(chunk.importance, chunk) for chunk in selected_durable_memories]
    selected_retrieved_memory = [
        (score, chunk)
        for score, chunk in memory_chunks
        if chunk.source not in durable_sources
    ][: max(top_k - len(selected_durable_memory), 0)]

    print("# Holo Context Pack")
    print()
    seed = canonical_seed()
    if seed:
        print("## Seed")
        print(seed)
        print()

    print("## Internal State Snapshot")
    print("```json")
    print(
        json.dumps(
            {
                "query_mode": state["query_mode"],
                "preferred_first_person": state["voice_state"]["preferred_first_person"],
                "default_path": state["habit_state"]["default_path"],
                "drift_level": state["drift_state"]["level"],
                "rewrite_state": state["rewrite_state"],
                "decoder_hints": state["decoder_hints"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    print("```")
    print()

    if selected_voice_guard:
        print("## Active Voice Guard")
        for line in selected_voice_guard:
            print(f"- {line}")
        print()

    if selected_persona:
        print("## Always-On Persona Anchors")
        for score, chunk in selected_persona:
            heading = chunk_heading(chunk)
            print(f"### {chunk.source} | {heading or chunk.kind} | score={score:.4f}")
            print(chunk.text.strip())
            print()

    if selected_durable_memory:
        print("## Durable Memory")
        for score, chunk in selected_durable_memory:
            tags = chunk.meta.get("tags", []) if isinstance(chunk.meta, dict) else []
            print(f"### {chunk.kind} | {chunk.source} | score={score:.4f}")
            if tags:
                print("tags: " + ", ".join(tags))
            print(chunk.text.strip())
            print()

    if selected_retrieved_memory:
        print("## Retrieved Memory")
        for score, chunk in selected_retrieved_memory:
            tags = chunk.meta.get("tags", []) if isinstance(chunk.meta, dict) else []
            print(f"### {chunk.kind} | {chunk.source} | score={score:.4f}")
            if tags:
                print("tags: " + ", ".join(tags))
            print(chunk.text.strip())
            print()


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Local RAG memory helper for the local subject profile")
    subparsers = parser.add_subparsers(dest="command", required=True)

    add_parser = subparsers.add_parser("add", help="Add a structured memory entry")
    add_parser.add_argument("--kind", required=True, choices=sorted(STRUCTURED_KINDS))
    add_parser.add_argument("--text", required=True)
    add_parser.add_argument("--tags", nargs="*", default=[])
    add_parser.add_argument("--source", default="manual")
    add_parser.add_argument("--importance", type=float, default=0.75)
    add_parser.add_argument("--status", choices=sorted(STORE_PATHS), default="durable")
    add_parser.add_argument("--confidence", type=float)

    consolidate_parser = subparsers.add_parser("consolidate", help="Turn observations into candidate memories")
    consolidate_parser.add_argument("--text", action="append", required=True)
    consolidate_parser.add_argument("--tags", nargs="*", default=[])
    consolidate_parser.add_argument("--source", default="observation")
    consolidate_parser.add_argument("--dry-run", action="store_true")

    observe_parser = subparsers.add_parser("observe-turn", help="Observe a user turn and optional reply, then distill candidate memory signals")
    observe_parser.add_argument("--user", required=True)
    observe_parser.add_argument("--reply", default=None)
    observe_parser.add_argument("--tags", nargs="*", default=[])
    observe_parser.add_argument("--source", default="chat.turn")
    observe_parser.add_argument("--dry-run", action="store_true")

    archive_parser = subparsers.add_parser("archive-turn", help="Append one full user/reply pair into the conversation archive")
    archive_parser.add_argument("--user", required=True)
    archive_parser.add_argument("--reply", required=True)
    archive_parser.add_argument("--tags", nargs="*", default=[])
    archive_parser.add_argument("--source", default="chat.turn")
    archive_parser.add_argument("--turn-id", default=None)
    archive_parser.add_argument("--json", action="store_true")

    show_archive_parser = subparsers.add_parser("show-archive", help="Inspect recently archived conversation turns")
    show_archive_parser.add_argument("--limit", type=int, default=12)
    show_archive_parser.add_argument("--channel", default=None)
    show_archive_parser.add_argument("--source", default=None)
    show_archive_parser.add_argument("--json", action="store_true")

    backfill_archive_parser = subparsers.add_parser("backfill-archive", help="Backfill the archive from holo_host.sqlite3")
    backfill_archive_parser.add_argument("--db-path", default=None)
    backfill_archive_parser.add_argument("--dry-run", action="store_true")
    backfill_archive_parser.add_argument("--json", action="store_true")

    dream_parser = subparsers.add_parser("dream-cycle", help="Replay archived turns into candidate memory and callback candidates")
    dream_parser.add_argument("--sample-size", type=int, default=6)
    dream_parser.add_argument("--seed", default=None)
    dream_parser.add_argument("--dry-run", action="store_true")
    dream_parser.add_argument("--json", action="store_true")

    think_parser = subparsers.add_parser("think-cycle", help="Spin one internal thought pass from recent archive")
    think_parser.add_argument("--sample-size", type=int, default=4)
    think_parser.add_argument("--seed", default=None)
    think_parser.add_argument("--dry-run", action="store_true")
    think_parser.add_argument("--json", action="store_true")

    reflect_parser = subparsers.add_parser("reflect-cycle", help="Condense repeated thought motifs into reflection summaries")
    reflect_parser.add_argument("--window-hours", type=float, default=12.0)
    reflect_parser.add_argument("--dry-run", action="store_true")
    reflect_parser.add_argument("--json", action="store_true")

    callbacks_parser = subparsers.add_parser("show-callbacks", help="Inspect callback candidates produced by replay/dream")
    callbacks_parser.add_argument("--limit", type=int, default=12)
    callbacks_parser.add_argument("--json", action="store_true")

    thoughts_parser = subparsers.add_parser("show-thoughts", help="Inspect recent internal thought-stream rows")
    thoughts_parser.add_argument("--limit", type=int, default=12)
    thoughts_parser.add_argument("--json", action="store_true")

    initiatives_parser = subparsers.add_parser("show-initiatives", help="Inspect initiative candidates")
    initiatives_parser.add_argument("--limit", type=int, default=12)
    initiatives_parser.add_argument("--json", action="store_true")

    initiative_cycle_parser = subparsers.add_parser("initiative-cycle", help="Refresh outbound initiative candidates from thoughts and callbacks")
    initiative_cycle_parser.add_argument("--dry-run", action="store_true")
    initiative_cycle_parser.add_argument("--json", action="store_true")

    artifact_parser = subparsers.add_parser("ingest-artifact", help="Read a local text/document/image artifact and distill it into memory")
    artifact_parser.add_argument("--path", required=True)
    artifact_parser.add_argument("--note", default=None)
    artifact_parser.add_argument("--tags", nargs="*", default=[])
    artifact_parser.add_argument("--source", default="artifact.observe")
    artifact_parser.add_argument("--dry-run", action="store_true")
    artifact_parser.add_argument("--json", action="store_true")

    sidecar_parser = subparsers.add_parser("sidecar-turn", help="Prepare a black-box sidecar addendum and optionally repair a returned draft")
    sidecar_parser.add_argument("--user", required=True)
    sidecar_parser.add_argument("--draft", default=None)
    sidecar_parser.add_argument("--tags", nargs="*", default=[])
    sidecar_parser.add_argument("--source", default="sidecar.turn")
    sidecar_parser.add_argument("--top-k", type=int, default=4)
    sidecar_parser.add_argument("--max-passes", type=int, default=2)
    sidecar_parser.add_argument("--dry-run", action="store_true")
    sidecar_parser.add_argument("--json", action="store_true")

    export_parser = subparsers.add_parser("export-snapshot", help="Write a portable self-memory snapshot for revival in another host")
    export_parser.add_argument("--path", default=None)
    export_parser.add_argument("--label", default=None)
    export_parser.add_argument("--query", default=None)
    export_parser.add_argument("--json", action="store_true")

    import_parser = subparsers.add_parser("import-snapshot", help="Restore or merge a portable self-memory snapshot")
    import_parser.add_argument("--path", required=True)
    import_parser.add_argument("--mode", choices=("merge", "replace"), default="merge")
    import_parser.add_argument("--restore-persona-files", action="store_true")
    import_parser.add_argument("--dry-run", action="store_true")
    import_parser.add_argument("--json", action="store_true")

    revive_parser = subparsers.add_parser("revive-packet", help="Generate a portable revive packet from live memory or a saved snapshot")
    revive_parser.add_argument("--query", default=None)
    revive_parser.add_argument("--path", default=None)
    revive_parser.add_argument("--json", action="store_true")

    review_parser = subparsers.add_parser("review-candidates", help="Review candidate memories")

    promote_parser = subparsers.add_parser("promote", help="Promote candidate memories into the durable store")
    promote_parser.add_argument("ids", nargs="+")

    reject_parser = subparsers.add_parser("reject", help="Reject candidate memories")
    reject_parser.add_argument("ids", nargs="+")

    query_parser = subparsers.add_parser("query", help="Retrieve matching chunks")
    query_parser.add_argument("query")
    query_parser.add_argument("--top-k", type=int, default=6)

    prompt_parser = subparsers.add_parser("prompt", help="Build a prompt-ready context pack")
    prompt_parser.add_argument("query")
    prompt_parser.add_argument("--top-k", type=int, default=5)

    audit_parser = subparsers.add_parser("audit", help="Inspect memory coverage and drift risks")
    audit_parser.add_argument("--query", default=None)

    state_parser = subparsers.add_parser("state", help="Build an internal machine-state snapshot")
    state_parser.add_argument("--query", default=None)
    state_parser.add_argument("--json", action="store_true")

    preflight_parser = subparsers.add_parser("preflight", help="Run the full pre-response gate on a draft")
    preflight_parser.add_argument("--query", required=True)
    preflight_parser.add_argument("--draft", required=True)
    preflight_parser.add_argument("--json", action="store_true")

    critic_parser = subparsers.add_parser("critic", help="Run a silent pre-response drift check on a draft")
    critic_parser.add_argument("--draft", required=True)
    critic_parser.add_argument("--query", default=None)

    reply_loop_parser = subparsers.add_parser("reply-loop", help="Repair a draft through preflight and deterministic rewrite passes")
    reply_loop_parser.add_argument("--query", required=True)
    reply_loop_parser.add_argument("--draft", required=True)
    reply_loop_parser.add_argument("--json", action="store_true")
    reply_loop_parser.add_argument("--max-passes", type=int, default=2)

    args = parser.parse_args(argv)

    if args.command == "add":
        add_memory(args.kind, args.text, args.tags, args.source, args.importance, args.status, args.confidence)
        return 0
    if args.command == "consolidate":
        command_consolidate(args.text, args.tags, args.source, args.dry_run)
        return 0
    if args.command == "observe-turn":
        command_observe_turn(args.user, reply=args.reply, tags=args.tags, source=args.source, dry_run=args.dry_run)
        return 0
    if args.command == "archive-turn":
        command_archive_turn(args.user, reply=args.reply, tags=args.tags, source=args.source, turn_id=args.turn_id, as_json=args.json)
        return 0
    if args.command == "show-archive":
        command_show_archive(limit=args.limit, as_json=args.json, channel=args.channel, source=args.source)
        return 0
    if args.command == "backfill-archive":
        command_backfill_archive(args.db_path, dry_run=args.dry_run, as_json=args.json)
        return 0
    if args.command == "dream-cycle":
        command_dream_cycle(sample_size=args.sample_size, seed=args.seed, dry_run=args.dry_run, as_json=args.json)
        return 0
    if args.command == "think-cycle":
        command_think_cycle(sample_size=args.sample_size, seed=args.seed, dry_run=args.dry_run, as_json=args.json)
        return 0
    if args.command == "reflect-cycle":
        command_reflect_cycle(window_hours=args.window_hours, dry_run=args.dry_run, as_json=args.json)
        return 0
    if args.command == "show-callbacks":
        command_show_callbacks(limit=args.limit, as_json=args.json)
        return 0
    if args.command == "show-thoughts":
        command_show_thoughts(limit=args.limit, as_json=args.json)
        return 0
    if args.command == "show-initiatives":
        command_show_initiatives(limit=args.limit, as_json=args.json)
        return 0
    if args.command == "initiative-cycle":
        result = initiative_cycle_result(dry_run=args.dry_run)
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print("# Initiative Cycle" + (" (dry-run)" if args.dry_run else ""))
            print(f"- staged: {result['staged']}")
            print(f"- initiative_added: {result['initiative_added']}")
        return 0
    if args.command == "ingest-artifact":
        command_ingest_artifact(
            args.path,
            note=args.note,
            tags=args.tags,
            source=args.source,
            dry_run=args.dry_run,
            as_json=args.json,
        )
        return 0
    if args.command == "sidecar-turn":
        command_sidecar_turn(
            args.user,
            draft=args.draft,
            tags=args.tags,
            source=args.source,
            top_k=args.top_k,
            max_passes=args.max_passes,
            dry_run=args.dry_run,
            as_json=args.json,
        )
        return 0
    if args.command == "export-snapshot":
        command_export_snapshot(args.path, label=args.label, query=args.query, as_json=args.json)
        return 0
    if args.command == "import-snapshot":
        command_import_snapshot(
            args.path,
            mode=args.mode,
            dry_run=args.dry_run,
            restore_persona=args.restore_persona_files,
            as_json=args.json,
        )
        return 0
    if args.command == "revive-packet":
        command_revive_packet(args.query, snapshot_path=args.path, as_json=args.json)
        return 0
    if args.command == "review-candidates":
        command_review_candidates()
        return 0
    if args.command == "promote":
        command_promote(args.ids)
        return 0
    if args.command == "reject":
        command_reject(args.ids)
        return 0
    if args.command == "query":
        command_query(args.query, args.top_k)
        return 0
    if args.command == "prompt":
        command_prompt(args.query, args.top_k)
        return 0
    if args.command == "audit":
        command_audit(args.query)
        return 0
    if args.command == "state":
        command_state(args.query, args.json)
        return 0
    if args.command == "preflight":
        command_preflight(args.query, args.draft, args.json)
        return 0
    if args.command == "critic":
        command_critic(args.draft, args.query)
        return 0
    if args.command == "reply-loop":
        command_reply_loop(args.query, args.draft, args.json, args.max_passes)
        return 0

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
