#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import os
import re
import sys
import tempfile
import time
from pathlib import Path
from types import ModuleType

REPO_ROOT = Path(
    os.environ.get("HOLO_REPO_ROOT", str(Path(__file__).resolve().parents[2]))
).resolve()
RAG_MEMORY_PATH = REPO_ROOT / "holo_memory_library" / "rag_memory.py"
CACHE_DIR = Path(
    os.environ.get(
        "HOLO_CODEX_HOOK_CACHE_DIR",
        str(Path(tempfile.gettempdir()) / "holo_codex_hook_cache"),
    )
).resolve()
LATEST_PROMPT_PATH = CACHE_DIR / "latest_prompt.json"
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


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f".{path.name}.tmp")
    temp_path.write_text(text, encoding="utf-8")
    temp_path.replace(path)


def load_payload() -> dict:
    try:
        return json.load(sys.stdin)
    except json.JSONDecodeError:
        return {}


def in_holo_repo(cwd: str | None) -> bool:
    if not cwd:
        return False
    try:
        current = Path(cwd).resolve()
    except OSError:
        return False
    return current == REPO_ROOT or REPO_ROOT in current.parents


def load_rag_memory() -> ModuleType:
    spec = importlib.util.spec_from_file_location("holo_rag_memory", RAG_MEMORY_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load {RAG_MEMORY_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def turn_cache_path(turn_id: str) -> Path:
    return CACHE_DIR / f"{turn_id}.json"


def normalize_prompt_text(text: str | None) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def strip_embedded_runtime_context(text: str | None) -> str:
    cleaned = normalize_prompt_text(text)
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
    return normalize_prompt_text(cleaned)


def extract_user_turn(prompt: str | None) -> str:
    text = normalize_prompt_text(prompt)
    if not text:
        return ""
    if RUNTIME_MESSAGE_MARKER not in text:
        return strip_embedded_runtime_context(text)
    if not any(hint in text for hint in RUNTIME_PROMPT_HINTS[:-1]):
        return strip_embedded_runtime_context(text)

    segment = text.split(RUNTIME_MESSAGE_MARKER, 1)[1].strip()
    stop_index = -1
    for marker in RUNTIME_MESSAGE_STOP_MARKERS:
        index = segment.find(marker)
        if index != -1 and (stop_index == -1 or index < stop_index):
            stop_index = index
    if stop_index != -1:
        segment = segment[:stop_index].strip()
    segment = strip_embedded_runtime_context(segment)
    return segment or strip_embedded_runtime_context(text)


def store_turn_prompt(turn_id: str | None, prompt: str) -> None:
    prompt = extract_user_turn(prompt)
    if not turn_id or not prompt.strip():
        return
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    payload = {"prompt": prompt, "saved_at": time.time()}
    atomic_write_text(turn_cache_path(turn_id), json.dumps(payload, ensure_ascii=False))
    atomic_write_text(LATEST_PROMPT_PATH, json.dumps({**payload, "turn_id": turn_id}, ensure_ascii=False))


def load_turn_prompt(turn_id: str | None) -> str | None:
    candidates: list[Path] = []
    if turn_id:
        candidates.append(turn_cache_path(turn_id))
    candidates.append(LATEST_PROMPT_PATH)
    now = time.time()
    for path in candidates:
        if not path.exists():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        prompt = extract_user_turn(str(payload.get("prompt", "")).strip())
        saved_at = float(payload.get("saved_at", 0.0))
        if not prompt:
            continue
        if path == LATEST_PROMPT_PATH and now - saved_at > 180:
            continue
        return prompt
    return None


def clear_turn_prompt(turn_id: str | None) -> None:
    if turn_id:
        path = turn_cache_path(turn_id)
        if path.exists():
            try:
                path.unlink()
            except OSError:
                pass
    if LATEST_PROMPT_PATH.exists():
        try:
            payload = json.loads(LATEST_PROMPT_PATH.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            payload = {}
        latest_turn_id = str(payload.get("turn_id", "")).strip()
        if not turn_id or not latest_turn_id or latest_turn_id == turn_id:
            try:
                LATEST_PROMPT_PATH.unlink()
            except OSError:
                return
