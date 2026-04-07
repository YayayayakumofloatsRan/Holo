from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import os
import re
import subprocess
import sys
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from queue import Empty
from typing import Any
from urllib import error, parse, request

RICH_MEDIA_KINDS = {"image_ref", "attachment_ref", "file_ref", "video_ref", "voice_ref"}
ATOMIC_WRITE_RETRIES = 6
ATOMIC_WRITE_RETRY_DELAY_SECONDS = 0.05
GENERIC_MESSAGE_LABELS = {
    "",
    "文件",
    "图片",
    "视频",
    "语音",
    "聊天记录",
    "[文件]",
    "[图片]",
    "[视频]",
    "[语音]",
    "[聊天记录]",
}


@dataclass(slots=True)
class ChatTurn:
    chat_name: str
    text: str
    sender: str = ""
    channel: str = "wechat"
    is_group: bool = False
    mentioned: bool = False
    message_id: str = ""
    thread_key: str = ""
    ts: int | None = None
    source_ref: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def dedupe_key(self) -> str:
        stable_id = self.message_id.strip()
        if stable_id:
            seed = "\n".join(
                [
                    self.channel,
                    self.chat_name,
                    self.sender,
                    stable_id,
                    self.thread_key,
                ]
            )
        else:
            seed = "\n".join(
                [
                    self.channel,
                    self.chat_name,
                    self.sender,
                    self.thread_key,
                    self.text,
                    str(self.ts or ""),
                ]
            )
        return hashlib.sha1(seed.encode("utf-8")).hexdigest()

    def to_payload(self) -> dict[str, Any]:
        payload = {
            "chat_name": self.chat_name,
            "sender": self.sender,
            "text": self.text,
            "channel": self.channel,
            "is_group": self.is_group,
            "mentioned": self.mentioned,
        }
        if self.message_id:
            payload["message_id"] = self.message_id
        if self.thread_key:
            payload["thread_key"] = self.thread_key
        if self.ts is not None:
            payload["ts"] = self.ts
        if self.source_ref:
            payload["source_ref"] = self.source_ref
        if self.metadata:
            payload["metadata"] = self.metadata
        return payload


@dataclass(slots=True)
class HelperConfig:
    agent_url: str = "http://127.0.0.1:8000"
    timeout_seconds: int = 90
    poll_seconds: float = 2.0
    cooldown_seconds: int = 15
    draft_only: bool = True
    whitelist: list[str] = field(default_factory=list)
    pause_file: Path = Path("C:/wechat-helper/PAUSE")
    state_file: Path = Path("C:/wechat-helper/state.json")
    transport_state_file: Path = Path("C:/wechat-helper/transport_state.json")
    adapter: str = "json_inbox"
    inbox_dir: Path = Path("C:/wechat-helper/inbox")
    processed_dir: Path = Path("C:/wechat-helper/processed")
    outbox_file: Path = Path("C:/wechat-helper/outbox.jsonl")
    send_queue_dir: Path = Path("C:/wechat-helper/send_queue")
    sent_dir: Path = Path("C:/wechat-helper/sent")
    failed_dir: Path = Path("C:/wechat-helper/failed")
    receipt_dir: Path = Path("C:/wechat-helper/receipts")
    pywinauto_process_path: str = r"C:\Program Files\Tencent\WeChat\WeChat.exe"
    wcf_host: str = ""
    wcf_port: int = 10086
    wcf_debug: bool = False
    wcf_block: bool = True
    wcf_contact_cache_seconds: int = 300
    pyweixin_repo_path: str = ""
    watch_mode: str = "auto"
    allow_transport_fallback: bool = True
    passive_probe_enabled: bool = True
    passive_probe_interval_seconds: float = 20.0
    passive_probe_requires_foreground: bool = True


def _to_path(value: str | None, fallback: Path) -> Path:
    raw = value or str(fallback)
    if os.name != "nt" and re.match(r"^[A-Za-z]:[\\/]", raw):
        drive = raw[0].lower()
        tail = raw[2:].lstrip("\\/")
        normalized_tail = tail.replace("\\", "/")
        return Path("/mnt") / drive / normalized_tail
    return Path(raw)


def _default_config_candidates() -> list[Path]:
    candidates: list[Path] = []
    env_path = os.environ.get("HOLO_WECHAT_HELPER_CONFIG", "").strip()
    if env_path:
        candidates.append(Path(env_path).expanduser())
    for raw in ("C:/wechat-helper/wechat_helper.live.json", "C:/wechat-helper/wechat_helper.json"):
        candidates.append(_to_path(raw, Path(raw)))
    repo_root = Path(__file__).resolve().parent
    candidates.append(repo_root / "wechat_helper.live.json")
    candidates.append(repo_root / "wechat_helper.example.json")
    return candidates


def load_config(path: str | None) -> HelperConfig:
    if not path:
        for candidate in _default_config_candidates():
            if candidate.exists():
                path = str(candidate)
                break
        if not path:
            return HelperConfig()
    config_path = Path(path).expanduser()
    if not config_path.exists():
        raise FileNotFoundError(f"config not found: {config_path}")
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid helper config: {config_path}: {exc}") from exc
    return HelperConfig(
        agent_url=str(data.get("agent_url", "http://127.0.0.1:8000")).rstrip("/"),
        timeout_seconds=int(data.get("timeout_seconds", 90)),
        poll_seconds=float(data.get("poll_seconds", 2.0)),
        cooldown_seconds=int(data.get("cooldown_seconds", 15)),
        draft_only=bool(data.get("draft_only", True)),
        whitelist=[str(item) for item in data.get("whitelist", [])],
        pause_file=_to_path(data.get("pause_file"), Path("C:/wechat-helper/PAUSE")),
        state_file=_to_path(data.get("state_file"), Path("C:/wechat-helper/state.json")),
        transport_state_file=_to_path(data.get("transport_state_file"), Path("C:/wechat-helper/transport_state.json")),
        adapter=str(data.get("adapter", "json_inbox")),
        inbox_dir=_to_path(data.get("inbox_dir"), Path("C:/wechat-helper/inbox")),
        processed_dir=_to_path(data.get("processed_dir"), Path("C:/wechat-helper/processed")),
        outbox_file=_to_path(data.get("outbox_file"), Path("C:/wechat-helper/outbox.jsonl")),
        send_queue_dir=_to_path(data.get("send_queue_dir"), Path("C:/wechat-helper/send_queue")),
        sent_dir=_to_path(data.get("sent_dir"), Path("C:/wechat-helper/sent")),
        failed_dir=_to_path(data.get("failed_dir"), Path("C:/wechat-helper/failed")),
        receipt_dir=_to_path(data.get("receipt_dir"), Path("C:/wechat-helper/receipts")),
        pywinauto_process_path=str(
            data.get("pywinauto_process_path", r"C:\Program Files\Tencent\WeChat\WeChat.exe")
        ),
        wcf_host=str(data.get("wcf_host", "")).strip(),
        wcf_port=int(data.get("wcf_port", 10086)),
        wcf_debug=bool(data.get("wcf_debug", False)),
        wcf_block=bool(data.get("wcf_block", True)),
        wcf_contact_cache_seconds=int(data.get("wcf_contact_cache_seconds", 300)),
        pyweixin_repo_path=str(data.get("pyweixin_repo_path", "")).strip(),
        watch_mode=str(data.get("watch_mode", "auto")).strip() or "auto",
        allow_transport_fallback=bool(data.get("allow_transport_fallback", True)),
        passive_probe_enabled=bool(data.get("passive_probe_enabled", True)),
        passive_probe_interval_seconds=float(data.get("passive_probe_interval_seconds", 20.0)),
        passive_probe_requires_foreground=bool(data.get("passive_probe_requires_foreground", True)),
    )


class StateStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.data = self._load()

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {
                "seen_by_chat": {},
                "last_sent_at": {},
                "history_sync_by_chat": {},
                "last_outbound_by_chat": {},
            }
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            self._quarantine_corrupt_file()
            payload = {}
        payload.setdefault("seen_by_chat", {})
        payload.setdefault("last_sent_at", {})
        payload.setdefault("history_sync_by_chat", {})
        payload.setdefault("last_outbound_by_chat", {})
        return payload

    def _quarantine_corrupt_file(self) -> None:
        if not self.path.exists():
            return
        suffix = f".corrupt-{int(time.time() * 1000)}"
        target = self.path.with_name(f"{self.path.name}{suffix}")
        try:
            self.path.replace(target)
        except OSError:
            return

    def save(self) -> None:
        atomic_write_text(self.path, json.dumps(self.data, ensure_ascii=False, indent=2) + "\n")

    def already_seen(self, turn: ChatTurn) -> bool:
        return self.data["seen_by_chat"].get(turn.chat_name) == turn.dedupe_key()

    def remember(self, turn: ChatTurn) -> None:
        self.data["seen_by_chat"][turn.chat_name] = turn.dedupe_key()

    def can_send(self, chat_name: str, *, now: float, cooldown_seconds: int) -> bool:
        last_sent = float(self.data["last_sent_at"].get(chat_name, 0.0) or 0.0)
        return (now - last_sent) >= cooldown_seconds

    def mark_sent(self, chat_name: str, *, now: float) -> None:
        self.data["last_sent_at"][chat_name] = now

    def remember_outbound(
        self,
        chat_name: str,
        *,
        text: str,
        digest: str = "",
        bubbles: list[str] | None = None,
        now: float | None = None,
    ) -> None:
        clean_bubbles = [normalize_chat_text(part) for part in (bubbles or []) if normalize_chat_text(part)]
        if not clean_bubbles:
            normalized = normalize_chat_text(text)
            clean_bubbles = [normalized] if normalized else []
        bubble_digests = [
            visible_row_digest(chat_name, {"kind": "text", "text": bubble, "file_name": ""}) for bubble in clean_bubbles
        ]
        digests = [item for item in [digest] + bubble_digests if str(item).strip()]
        self.data["last_outbound_by_chat"][chat_name] = {
            "text": normalize_chat_text(text),
            "digest": digest or (digests[0] if digests else hashlib.sha1(text.encode("utf-8")).hexdigest()[:24]),
            "digests": dedupe_preserve_order(digests),
            "bubble_texts": clean_bubbles,
            "sent_at": int(now or time.time()),
        }

    def outbound_digest(self, chat_name: str) -> str:
        row = self.data["last_outbound_by_chat"].get(chat_name, {})
        if isinstance(row, dict):
            return str(row.get("digest", "") or "")
        return ""

    def outbound_digests(self, chat_name: str) -> list[str]:
        row = self.data["last_outbound_by_chat"].get(chat_name, {})
        if not isinstance(row, dict):
            return []
        values = row.get("digests", [])
        if isinstance(values, list):
            items = [str(value).strip() for value in values if str(value).strip()]
            if items:
                return items
        digest = str(row.get("digest", "") or "").strip()
        return [digest] if digest else []

    def last_outbound(self, chat_name: str) -> dict[str, Any]:
        row = self.data["last_outbound_by_chat"].get(chat_name, {})
        return dict(row) if isinstance(row, dict) else {}

    def last_history_sync_digest(self, chat_name: str) -> str:
        row = self.data["history_sync_by_chat"].get(chat_name, {})
        if isinstance(row, dict):
            return str(row.get("digest", "") or "")
        return ""

    def mark_history_synced(self, chat_name: str, *, digest: str, export_path: str, now: float | None = None) -> None:
        self.data["history_sync_by_chat"][chat_name] = {
            "digest": digest,
            "export_path": export_path,
            "synced_at": int(now or time.time()),
        }


class AgentClient:
    def __init__(self, base_url: str, *, timeout_seconds: int = 90):
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def get_json(self, path: str) -> dict[str, Any]:
        req = request.Request(self.base_url + path, method="GET")
        return self._execute(req)

    def post_json(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = request.Request(
            self.base_url + path,
            data=raw,
            headers={"Content-Type": "application/json; charset=utf-8"},
            method="POST",
        )
        return self._execute(req)

    def health(self) -> dict[str, Any]:
        return self.get_json("/health")

    def reply(self, turn: ChatTurn) -> dict[str, Any]:
        return self.post_json("/reply", turn.to_payload())

    def snapshot(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.post_json("/snapshot", payload)

    def restore_snapshot(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.post_json("/restore-snapshot", payload)

    def ingest_artifact(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.post_json("/ingest-artifact", payload)

    def revive_packet(self, *, path: str | None = None, query: str | None = None) -> dict[str, Any]:
        params = {}
        if path:
            params["path"] = path
        if query:
            params["query"] = query
        suffix = "/revive-packet"
        if params:
            suffix += "?" + parse.urlencode(params)
        return self.get_json(suffix)

    def _execute(self, req: request.Request) -> dict[str, Any]:
        parsed = parse.urlparse(req.full_url)
        opener = None
        if parsed.hostname in {"127.0.0.1", "localhost"}:
            opener = request.build_opener(request.ProxyHandler({}))
        try:
            execute = opener.open if opener is not None else request.urlopen
            with execute(req, timeout=self.timeout_seconds) as response:  # noqa: S310
                return json.loads(response.read().decode("utf-8"))
        except error.HTTPError as exc:  # noqa: PERF203
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"http {exc.code}: {detail}") from exc
        except error.URLError as exc:
            raise RuntimeError(f"agent unreachable: {exc}") from exc


def append_outbox_record(path: Path, record: dict[str, Any]) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    return record


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f".{path.name}.tmp-{os.getpid()}-{int(time.time() * 1000)}")
    try:
        temp_path.write_text(text, encoding="utf-8")
        last_exc: OSError | None = None
        for attempt in range(ATOMIC_WRITE_RETRIES):
            try:
                os.replace(temp_path, path)
                last_exc = None
                break
            except PermissionError as exc:
                last_exc = exc
                if attempt >= ATOMIC_WRITE_RETRIES - 1:
                    raise
                time.sleep(ATOMIC_WRITE_RETRY_DELAY_SECONDS * (attempt + 1))
        if last_exc is not None:
            raise last_exc
    finally:
        if temp_path.exists():
            temp_path.unlink(missing_ok=True)


def write_transport_state(
    config: HelperConfig,
    *,
    status: str,
    mode: str,
    transport: str,
    detail: str = "",
    error_type: str = "",
    heartbeat_only: bool = False,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "status": status,
        "mode": mode,
        "transport": transport,
        "watch_mode": config.watch_mode,
        "heartbeat_at": int(time.time()),
        "detail": detail,
        "error_type": error_type,
        "heartbeat_only": heartbeat_only,
    }
    if extra:
        payload.update(extra)
    atomic_write_text(config.transport_state_file, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    return payload


def rect_payload(rect: Any) -> dict[str, int]:
    left = int(getattr(rect, "left", 0) or 0)
    top = int(getattr(rect, "top", 0) or 0)
    right = int(getattr(rect, "right", 0) or 0)
    bottom = int(getattr(rect, "bottom", 0) or 0)
    return {
        "left": left,
        "top": top,
        "right": right,
        "bottom": bottom,
        "width": max(0, right - left),
        "height": max(0, bottom - top),
        "center_x": left + max(0, right - left) // 2,
        "center_y": top + max(0, bottom - top) // 2,
    }


class JsonInboxAdapter:
    def __init__(self, config: HelperConfig):
        self.inbox_dir = Path(config.inbox_dir)
        self.processed_dir = Path(config.processed_dir)
        self.outbox_file = Path(config.outbox_file)
        self.inbox_dir.mkdir(parents=True, exist_ok=True)
        self.processed_dir.mkdir(parents=True, exist_ok=True)
        self.outbox_file.parent.mkdir(parents=True, exist_ok=True)

    def poll_turns(self, limit: int = 10) -> list[tuple[ChatTurn, Path]]:
        items: list[tuple[ChatTurn, Path]] = []
        for path in sorted(self.inbox_dir.glob("*.json"))[:limit]:
            payload = json.loads(path.read_text(encoding="utf-8"))
            items.append((parse_turn(payload), path))
        return items

    def mark_processed(self, source: Path) -> None:
        target = self.processed_dir / source.name
        source.replace(target)

    def send_reply(self, turn: ChatTurn, text: str, *, draft_only: bool) -> dict[str, Any]:
        return self.send_bubbles(turn, [text], cadence_ms=[0], draft_only=draft_only)

    def send_bubbles(
        self,
        turn: ChatTurn,
        bubbles: list[str],
        *,
        cadence_ms: list[int] | None = None,
        draft_only: bool,
    ) -> dict[str, Any]:
        record = {
            "chat_name": turn.chat_name,
            "sender": turn.sender,
            "thread_key": turn.thread_key,
            "message_id": turn.message_id,
            "draft_only": draft_only,
            "text": " ".join(part.strip() for part in bubbles if str(part).strip()),
            "bubbles": [part.strip() for part in bubbles if str(part).strip()],
            "cadence_ms": list(cadence_ms or []),
            "ts": int(time.time()),
        }
        return append_outbox_record(self.outbox_file, record)


def current_stamp() -> str:
    return time.strftime("%Y%m%dT%H%M%S", time.localtime()) + f"-{int((time.time() % 1) * 1000):03d}"


class PyweixinReplyAdapter:
    def __init__(self, config: HelperConfig):
        self.config = config
        self.outbox_file = Path(config.outbox_file)
        self.outbox_file.parent.mkdir(parents=True, exist_ok=True)

    def send_reply(self, turn: ChatTurn, text: str, *, draft_only: bool) -> dict[str, Any]:
        return self.send_bubbles(turn, [text], cadence_ms=[0], draft_only=draft_only)

    def send_bubbles(
        self,
        turn: ChatTurn,
        bubbles: list[str],
        *,
        cadence_ms: list[int] | None = None,
        draft_only: bool,
    ) -> dict[str, Any]:
        clean_bubbles = [part.strip() for part in bubbles if str(part).strip()]
        record = {
            "chat_name": turn.chat_name,
            "sender": turn.sender,
            "thread_key": turn.thread_key,
            "message_id": turn.message_id,
            "draft_only": draft_only,
            "text": " ".join(clean_bubbles),
            "bubbles": clean_bubbles,
            "cadence_ms": list(cadence_ms or []),
            "ts": int(time.time()),
            "source": "pyweixin_live",
        }
        append_outbox_record(self.outbox_file, record)
        if draft_only:
            return record
        results: list[dict[str, Any]] = []
        gaps = list(cadence_ms or [])
        for index, bubble in enumerate(clean_bubbles or [record["text"]]):
            if index > 0:
                delay_ms = gaps[index] if index < len(gaps) else 420
                time.sleep(max(0.0, float(delay_ms) / 1000.0))
            send_result = send_via_pyweixin(
                self.config,
                chat_name=turn.chat_name,
                text=bubble,
                search_pages=0,
                clear=True,
                send_delay=0.18,
            )
            results.append(send_result)
        record["send_result"] = {
            "ok": all(bool(item.get("ok", False)) for item in results) if results else False,
            "bubbles_sent": len(results),
            "results": results,
        }
        return record


class PyweixinDialogAdapter:
    def __init__(self, config: HelperConfig, loaded: dict[str, Any]):
        self.config = config
        self.loaded = loaded
        self.outbox_file = Path(config.outbox_file)
        self.outbox_file.parent.mkdir(parents=True, exist_ok=True)
        self._dialogs: dict[str, Any] = {}
        self._last_prime_at = 0.0

    def ensure_dialog(self, chat_name: str) -> Any:
        dialog = self._dialogs.get(chat_name)
        if dialog is not None:
            try:
                if dialog.exists(timeout=0.2):
                    return dialog
            except Exception:  # noqa: BLE001
                pass
        Navigator = self.loaded["Navigator"]
        last_exc: Exception | None = None
        for attempt in range(3):
            try:
                dialog = open_pyweixin_dialog_local(self.loaded, chat_name, window_minimize=True)
                self._dialogs[chat_name] = dialog
                return dialog
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                if _is_pyweixin_transient_error(exc):
                    self._maybe_prime(wait_seconds=1.0)
                if attempt < 2:
                    time.sleep(0.8)
        raise RuntimeError(f"unable to open dedicated dialog for {chat_name}: {last_exc}") from last_exc

    def _maybe_prime(self, *, wait_seconds: float, min_interval: float = 20.0) -> None:
        now = time.time()
        if now - self._last_prime_at < min_interval:
            return
        self._last_prime_at = now
        try:
            prime_pyweixin_runtime(self.config, restart_weixin=False, wait_seconds=wait_seconds)
        except Exception:  # noqa: BLE001
            return

    def close(self) -> None:
        for dialog in self._dialogs.values():
            try:
                dialog.close()
            except Exception:  # noqa: BLE001
                continue
        self._dialogs.clear()

    def send_reply(self, turn: ChatTurn, text: str, *, draft_only: bool) -> dict[str, Any]:
        return self.send_bubbles(turn, [text], cadence_ms=[0], draft_only=draft_only)

    def send_bubbles(
        self,
        turn: ChatTurn,
        bubbles: list[str],
        *,
        cadence_ms: list[int] | None = None,
        draft_only: bool,
    ) -> dict[str, Any]:
        clean_bubbles = [part.strip() for part in bubbles if str(part).strip()]
        record = {
            "chat_name": turn.chat_name,
            "sender": turn.sender,
            "thread_key": turn.thread_key,
            "message_id": turn.message_id,
            "draft_only": draft_only,
            "text": " ".join(clean_bubbles),
            "bubbles": clean_bubbles,
            "cadence_ms": list(cadence_ms or []),
            "ts": int(time.time()),
            "source": "pyweixin_dialog_live",
        }
        append_outbox_record(self.outbox_file, record)
        if draft_only:
            return record

        pyautogui = importlib.import_module("pyautogui")
        pyautogui.FAILSAFE = False
        try:
            import win32con
            import win32gui
        except ImportError as exc:  # pragma: no cover - Windows-only helper
            raise RuntimeError("pywin32 is required for pyweixin dialog sending") from exc

        dialog = self.ensure_dialog(turn.chat_name)
        input_edit = dialog.child_window(**self.loaded["Edits"].InputEdit)
        if not input_edit.exists(timeout=0.3):
            raise RuntimeError(f"dialog input field is unavailable for {turn.chat_name}")

        results: list[dict[str, Any]] = []
        gaps = list(cadence_ms or [])
        dialog.restore()
        time.sleep(0.18)
        for index, bubble in enumerate(clean_bubbles or [record["text"]]):
            if index > 0:
                delay_ms = gaps[index] if index < len(gaps) else 420
                time.sleep(max(0.0, float(delay_ms) / 1000.0))
            input_edit.set_text(bubble)
            pyautogui.hotkey("alt", "s", _pause=False)
            results.append({"ok": True, "bubble": bubble})
            time.sleep(0.12)
        try:
            win32gui.SendMessage(dialog.handle, win32con.WM_SYSCOMMAND, win32con.SC_MINIMIZE, 0)
        except Exception:  # noqa: BLE001
            pass
        record["send_result"] = {
            "ok": True,
            "bubbles_sent": len(results),
            "results": results,
        }
        return record


def display_name_for_contact(contact: dict[str, Any]) -> str:
    for key in ("remark", "name", "code", "wxid"):
        value = str(contact.get(key, "") or "").strip()
        if value:
            return value
    return ""


def contact_match_score(contact: dict[str, Any], needle: str) -> int:
    query = needle.strip().lower()
    if not query:
        return 1
    score = 0
    weighted_fields = (
        ("remark", 400),
        ("name", 300),
        ("code", 200),
        ("wxid", 100),
    )
    for key, base in weighted_fields:
        value = str(contact.get(key, "") or "").strip()
        if not value:
            continue
        lowered = value.lower()
        if lowered == query:
            score = max(score, base + 50)
        elif lowered.startswith(query):
            score = max(score, base + 25)
        elif query in lowered:
            score = max(score, base + 10)
    return score


def best_contact_match(contacts: list[dict[str, Any]], needle: str) -> dict[str, Any] | None:
    best: tuple[int, str, dict[str, Any]] | None = None
    for contact in contacts:
        score = contact_match_score(contact, needle)
        if score <= 0:
            continue
        label = display_name_for_contact(contact)
        candidate = (score, label.lower(), contact)
        if best is None or candidate[0] > best[0] or (candidate[0] == best[0] and candidate[1] < best[1]):
            best = candidate
    return best[2] if best else None


def contact_preview(contact: dict[str, Any]) -> dict[str, Any]:
    return {
        "label": display_name_for_contact(contact),
        "remark": str(contact.get("remark", "") or ""),
        "name": str(contact.get("name", "") or ""),
        "code": str(contact.get("code", "") or ""),
        "wxid": str(contact.get("wxid", "") or ""),
    }


def chat_turn_from_wcf_msg(msg: Any, *, contacts_by_wxid: dict[str, dict[str, Any]], self_wxid: str) -> ChatTurn | None:
    if not getattr(msg, "is_text", lambda: False)():
        return None
    if getattr(msg, "from_self", lambda: False)():
        return None

    sender_wxid = str(getattr(msg, "sender", "") or "").strip()
    roomid = str(getattr(msg, "roomid", "") or "").strip()
    receiver = roomid or sender_wxid
    sender_contact = contacts_by_wxid.get(sender_wxid, {})
    room_contact = contacts_by_wxid.get(roomid, {})

    is_group = bool(getattr(msg, "from_group", lambda: False)())
    mentioned = bool(getattr(msg, "is_at", lambda _wxid: False)(self_wxid)) if is_group and self_wxid else False
    chat_name = display_name_for_contact(room_contact) if roomid else display_name_for_contact(sender_contact)
    sender_name = display_name_for_contact(sender_contact) or sender_wxid

    if not chat_name:
        chat_name = receiver or "微信联系人"

    text = str(getattr(msg, "content", "") or "").strip()
    if not text:
        return None

    return ChatTurn(
        chat_name=chat_name,
        text=text,
        sender=sender_name,
        channel="wechat",
        is_group=is_group,
        mentioned=mentioned,
        message_id=str(getattr(msg, "id", "") or "").strip(),
        thread_key=receiver,
        ts=int(getattr(msg, "ts", 0) or 0) or None,
        source_ref="wcf",
        metadata={
            "receiver": receiver,
            "wxid": sender_wxid,
            "roomid": roomid,
            "msg_type": int(getattr(msg, "type", 0) or 0),
        },
    )


def _version_tuple(raw: str) -> tuple[int, ...]:
    parts = re.findall(r"\d+", raw or "")
    return tuple(int(part) for part in parts)


def _windows_file_version(path: str) -> str:
    raw = str(path or "").strip()
    if not raw:
        return ""
    if os.name != "nt":
        return ""
    command = [
        "powershell",
        "-NoProfile",
        "-Command",
        f"(Get-Item '{raw}').VersionInfo.FileVersion",
    ]
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=6,
            check=False,
        )
    except Exception:  # noqa: BLE001
        return ""
    if completed.returncode != 0:
        return ""
    return completed.stdout.strip()


def wcf_runtime_info(config: HelperConfig) -> dict[str, Any]:
    info: dict[str, Any] = {
        "wcf_installed": False,
        "wcf_version": "",
        "client_path": config.pywinauto_process_path,
        "client_name": Path(config.pywinauto_process_path).name,
        "client_version": "",
        "compatibility": "unknown",
        "reason": "",
    }
    try:
        import wcferry  # type: ignore
    except ImportError:
        info["compatibility"] = "missing_wcferry"
        info["reason"] = "wcferry is not installed in the active Windows Python."
        return info

    info["wcf_installed"] = True
    info["wcf_version"] = str(getattr(wcferry, "__version__", "") or "")
    info["client_version"] = _windows_file_version(config.pywinauto_process_path)

    wcf_version = info["wcf_version"]
    client_name = str(info["client_name"] or "").lower()
    client_version = str(info["client_version"] or "")
    if not wcf_version:
        info["compatibility"] = "unknown"
        info["reason"] = "wcferry version is unavailable."
        return info
    if wcf_version.startswith("39."):
        if client_version and _version_tuple(client_version) >= (4, 0):
            info["compatibility"] = "incompatible"
            info["reason"] = (
                f"installed wcferry {wcf_version} is the 39.x line documented for WeChat/微信 3.9.x, "
                f"but current client {client_name or 'wechat'} is {client_version}."
            )
            return info
        if client_name == "weixin.exe" and not client_version:
            info["compatibility"] = "suspect"
            info["reason"] = (
                f"installed wcferry {wcf_version} targets the 39.x / 3.9.x client line; "
                f"current executable is {client_name}, which is commonly newer than that lane."
            )
            return info
    info["compatibility"] = "compatible_or_unknown"
    info["reason"] = "no obvious local version mismatch detected"
    return info


class WcfAdapter:
    def __init__(self, config: HelperConfig):
        self.config = config
        self.outbox_file = Path(config.outbox_file)
        self.outbox_file.parent.mkdir(parents=True, exist_ok=True)
        self._client: Any | None = None
        self._self_wxid = ""
        self._contacts: list[dict[str, Any]] = []
        self._contacts_loaded_at = 0.0

    def _load_wcf_class(self) -> Any:
        try:
            from wcferry import Wcf  # type: ignore
        except ImportError as exc:  # pragma: no cover - Windows-only dependency
            raise SystemExit("wcferry is required for WCF mode; install it on Windows first.") from exc
        return Wcf

    def _ensure_local_wcf_compatibility(self) -> None:
        if self.config.wcf_host:
            return
        info = wcf_runtime_info(self.config)
        if info["compatibility"] == "incompatible":
            raise RuntimeError(str(info["reason"]))

    def client(self) -> Any:
        if self._client is None:
            self._ensure_local_wcf_compatibility()
            Wcf = self._load_wcf_class()
            host = self.config.wcf_host or None
            self._client = Wcf(
                host=host,
                port=self.config.wcf_port,
                debug=self.config.wcf_debug,
                block=self.config.wcf_block,
            )
            if hasattr(self._client, "is_login") and not self._client.is_login():
                raise RuntimeError("wcf is connected but WeChat is not logged in")
            self._self_wxid = str(getattr(self._client, "get_self_wxid")() or "")
        return self._client

    def close(self) -> None:
        if self._client is None:
            return
        try:
            self._client.cleanup()
        except Exception:  # noqa: BLE001
            pass
        self._client = None

    def self_wxid(self) -> str:
        if not self._self_wxid:
            self._self_wxid = str(getattr(self.client(), "get_self_wxid")() or "")
        return self._self_wxid

    def refresh_contacts(self, *, force: bool = False) -> list[dict[str, Any]]:
        now = time.time()
        if force or not self._contacts or (now - self._contacts_loaded_at) >= self.config.wcf_contact_cache_seconds:
            self._contacts = list(getattr(self.client(), "get_contacts")() or [])
            self._contacts_loaded_at = now
        return self._contacts

    def list_contacts(self, *, needle: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
        query = str(needle or "").strip()
        contacts = self.refresh_contacts()
        ranked: list[tuple[int, str, dict[str, Any]]] = []
        for contact in contacts:
            score = contact_match_score(contact, query)
            if query and score <= 0:
                continue
            ranked.append((score, display_name_for_contact(contact).lower(), contact))
        ranked.sort(key=lambda item: (-item[0], item[1]))
        rows: list[dict[str, Any]] = []
        for score, _label, contact in ranked[:limit]:
            row = contact_preview(contact)
            row["score"] = score
            rows.append(row)
        return rows

    def start_receiving(self) -> None:
        if not getattr(self.client(), "is_receiving_msg")():
            ok = getattr(self.client(), "enable_receiving_msg")()
            if not ok:
                raise RuntimeError("wcf failed to enable message receiving")

    def next_turn(self) -> ChatTurn | None:
        raw = getattr(self.client(), "get_msg")(True)
        turn = chat_turn_from_wcf_msg(
            raw,
            contacts_by_wxid={str(item.get("wxid", "") or ""): item for item in self.refresh_contacts()},
            self_wxid=self.self_wxid(),
        )
        return turn

    def resolve_receiver(self, turn: ChatTurn) -> str:
        metadata = turn.metadata or {}
        for key in ("receiver", "roomid", "wxid"):
            value = str(metadata.get(key, "") or "").strip()
            if value:
                return value
        if turn.thread_key:
            return turn.thread_key
        query = turn.chat_name.strip()
        if query:
            match = best_contact_match(self.refresh_contacts(), query)
            if match:
                return str(match.get("wxid", "") or "").strip()
        return ""

    def send_reply(self, turn: ChatTurn, text: str, *, draft_only: bool) -> dict[str, Any]:
        return self.send_bubbles(turn, [text], cadence_ms=[0], draft_only=draft_only)

    def send_bubbles(
        self,
        turn: ChatTurn,
        bubbles: list[str],
        *,
        cadence_ms: list[int] | None = None,
        draft_only: bool,
    ) -> dict[str, Any]:
        receiver = self.resolve_receiver(turn)
        clean_bubbles = [part.strip() for part in bubbles if str(part).strip()]
        record = {
            "chat_name": turn.chat_name,
            "sender": turn.sender,
            "thread_key": turn.thread_key,
            "message_id": turn.message_id,
            "draft_only": draft_only,
            "text": " ".join(clean_bubbles),
            "bubbles": clean_bubbles,
            "cadence_ms": list(cadence_ms or []),
            "ts": int(time.time()),
            "transport": "wcf",
            "receiver": receiver,
        }
        if draft_only:
            return append_outbox_record(self.outbox_file, record)
        if not receiver:
            raise RuntimeError(f"unable to resolve wxid/roomid for {turn.chat_name}")
        results: list[int] = []
        gaps = list(cadence_ms or [])
        for index, bubble in enumerate(clean_bubbles or [record["text"]]):
            if index > 0:
                delay_ms = gaps[index] if index < len(gaps) else 420
                time.sleep(max(0.0, float(delay_ms) / 1000.0))
            results.append(int(getattr(self.client(), "send_text")(bubble, receiver)))
        record["send_result"] = {
            "ok": all(status == 1 for status in results),
            "bubbles_sent": len(results),
            "statuses": results,
        }
        return append_outbox_record(self.outbox_file, record)


def parse_turn(payload: dict[str, Any]) -> ChatTurn:
    chat_name = str(payload.get("chat_name", "")).strip()
    text = str(payload.get("text", "")).strip()
    if not chat_name:
        raise ValueError("chat_name is required")
    return ChatTurn(
        chat_name=chat_name,
        text=text,
        sender=str(payload.get("sender", "")).strip(),
        channel=str(payload.get("channel", "wechat")).strip() or "wechat",
        is_group=bool(payload.get("is_group", False)),
        mentioned=bool(payload.get("mentioned", False)),
        message_id=str(payload.get("message_id", "")).strip(),
        thread_key=str(payload.get("thread_key", "")).strip(),
        ts=int(payload["ts"]) if payload.get("ts") not in (None, "") else None,
        source_ref=str(payload.get("source_ref", "")).strip(),
        metadata=payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {},
    )


def print_json(data: dict[str, Any]) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2))


def import_pyweixin(repo_path: str = "") -> dict[str, Any]:
    normalized_repo = str(repo_path or "").strip()
    if normalized_repo and normalized_repo not in sys.path:
        sys.path.insert(0, normalized_repo)
    try:
        pyweixin = importlib.import_module("pyweixin")
        tools_mod = importlib.import_module("pyweixin.WeChatTools")
        utils_mod = importlib.import_module("pyweixin.utils")
        uielements_mod = importlib.import_module("pyweixin.Uielements")
    except ImportError as exc:
        detail = f" from {normalized_repo}" if normalized_repo else ""
        raise SystemExit(f"pyweixin is required for this command; unable to import{detail}") from exc

    return {
        "repo_path": normalized_repo,
        "pyweixin": pyweixin,
        "Navigator": getattr(pyweixin, "Navigator"),
        "Messages": getattr(pyweixin, "Messages"),
        "Monitor": getattr(pyweixin, "Monitor"),
        "SystemSettings": getattr(pyweixin, "SystemSettings"),
        "GlobalConfig": getattr(pyweixin, "GlobalConfig"),
        "wx": getattr(tools_mod, "wx"),
        "Main_window": getattr(tools_mod, "Main_window"),
        "Edits": getattr(tools_mod, "Edits"),
        "Texts": getattr(tools_mod, "Texts"),
        "utils": utils_mod,
        "MenuItems": getattr(uielements_mod, "MenuItems")(),
        "SideBar": getattr(uielements_mod, "SideBar")(),
    }


def enumerate_qt_windows() -> list[dict[str, Any]]:
    try:
        import win32gui
        from pywinauto import Desktop
    except ImportError as exc:  # pragma: no cover - Windows-only helper
        raise SystemExit("pywinauto/pywin32 are required for pyweixin probing on Windows.") from exc

    desktop = Desktop(backend="uia")
    handles: list[int] = []
    pattern = re.compile(r"Qt\d+QWindowIcon")

    def cb(hwnd: int, _extra: Any) -> bool:
        try:
            if pattern.match(win32gui.GetClassName(hwnd)):
                handles.append(hwnd)
        except Exception:  # noqa: BLE001
            pass
        return True

    win32gui.EnumWindows(cb, None)
    rows: list[dict[str, Any]] = []
    for hwnd in handles:
        try:
            window = desktop.window(handle=hwnd)
            descendants = window.descendants()
            rows.append(
                {
                    "hwnd": int(hwnd),
                    "title": window.window_text(),
                    "win32_class": win32gui.GetClassName(hwnd),
                    "uia_class": window.class_name(),
                    "visible": bool(win32gui.IsWindowVisible(hwnd)),
                    "descendant_count": len(descendants),
                }
            )
        except Exception as exc:  # noqa: BLE001
            rows.append({"hwnd": int(hwnd), "error": str(exc)})
    return rows


def probe_pyweixin_state(config: HelperConfig) -> dict[str, Any]:
    loaded = import_pyweixin(config.pyweixin_repo_path)
    Navigator = loaded["Navigator"]
    wx = loaded["wx"]
    main_ui = loaded["Main_window"]
    edits = loaded["Edits"]

    payload: dict[str, Any] = {
        "repo_path": loaded["repo_path"],
        "qt_windows": enumerate_qt_windows(),
    }

    hwnd = int(wx.find_wx_window() or 0)
    payload["wx_find_window"] = {"hwnd": hwnd, "window_type": int(getattr(wx, "window_type", 1) or 1)}
    if not hwnd:
        return payload

    try:
        main_window = Navigator.open_weixin(is_maximize=False)
        search_edit = main_window.child_window(**edits.SearchEdit)
        session_list = main_window.child_window(**main_ui.SessionList)
        current_chat_edit = main_window.child_window(**edits.CurrentChatEdit)
        payload["open_weixin"] = {
            "ok": True,
            "title": main_window.window_text(),
            "class_name": main_window.class_name(),
            "handle": int(main_window.handle),
            "controls": {
                "search_edit": bool(search_edit.exists(timeout=0.2)),
                "session_list": bool(session_list.exists(timeout=0.2)),
                "current_chat_edit": bool(current_chat_edit.exists(timeout=0.2)),
            },
        }
        visible_texts: list[dict[str, Any]] = []
        for elem in main_window.descendants()[:120]:
            try:
                text = (elem.window_text() or "").strip()
                if not text:
                    continue
                visible_texts.append(
                    {
                        "text": text,
                        "class_name": str(getattr(elem.element_info, "class_name", "") or ""),
                        "control_type": str(getattr(elem.element_info, "control_type", "") or ""),
                        "automation_id": str(getattr(elem.element_info, "automation_id", "") or ""),
                    }
                )
            except Exception:  # noqa: BLE001
                continue
        payload["visible_texts"] = visible_texts[:40]
    except Exception as exc:  # noqa: BLE001
        payload["open_weixin"] = {
            "ok": False,
            "error_type": type(exc).__name__,
            "error": str(exc),
            "traceback": traceback.format_exc(limit=4),
        }
    return payload


def _normalize_wechat_text(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def pyweixin_find_send_button(main_window: Any) -> Any | None:
    for button in main_window.descendants(class_name="mmui::XOutlineButton"):
        try:
            if _normalize_wechat_text(button.window_text()).startswith("发送"):
                return button
        except Exception:  # noqa: BLE001
            continue
    for button in main_window.descendants(control_type="Button"):
        try:
            if _normalize_wechat_text(button.window_text()) == "发送":
                return button
        except Exception:  # noqa: BLE001
            continue
    return None


def _pyweixin_visible_messages_from_main(
    loaded: dict[str, Any],
    main: Any,
    *,
    chat_name: str,
    limit: int = 20,
    capture_dir: str | None = None,
) -> dict[str, Any]:
    msg_list = pyweixin_find_message_list(main)
    if msg_list is None:
        raise RuntimeError("message list not found in current chat")
    list_rect, rows = collect_pyweixin_visible_rows(
        main,
        msg_list,
        chat_name=chat_name,
        limit=limit,
        capture_dir=capture_dir,
        menu_items=loaded.get("MenuItems"),
        probe_unknown_directions=False,
    )
    return {
        "chat_name": chat_name,
        "current_chat": pyweixin_current_chat_name(main),
        "list_rect": list_rect,
        "message_count": len(rows),
        "messages": rows,
    }


def _pyweixin_visible_contains_text(payload: dict[str, Any], text: str) -> bool:
    needle = _normalize_wechat_text(text)
    if not needle:
        return False
    for row in payload.get("messages", []):
        haystacks = [
            _normalize_wechat_text(str(row.get("text", "") or "")),
            _normalize_wechat_text(str(row.get("text_preview", "") or "")),
        ]
        if any(needle and needle in haystack for haystack in haystacks):
            return True
    return False


def _wait_for_pyweixin_visible_text(
    loaded: dict[str, Any],
    *,
    chat_name: str,
    text: str,
    attempts: int = 5,
    delay_seconds: float = 0.35,
) -> dict[str, Any]:
    last_payload: dict[str, Any] | None = None
    for attempt in range(max(1, attempts)):
        main = pyweixin_open_main(loaded)
        current_chat = pyweixin_current_chat_name(main)
        if current_chat != chat_name:
            raise RuntimeError(f"send verification failed: expected {chat_name}, got {current_chat or '<empty>'}")
        last_payload = _pyweixin_visible_messages_from_main(loaded, main, chat_name=chat_name, limit=12)
        if _pyweixin_visible_contains_text(last_payload, text):
            return last_payload
        if attempt + 1 < attempts:
            time.sleep(delay_seconds)
    raise RuntimeError(f"send verification failed: {chat_name} does not show the new message yet")


def send_current_chat_via_pyweixin(
    *,
    loaded: dict[str, Any],
    chat_name: str,
    text: str,
    clear: bool,
    send_delay: float,
) -> dict[str, Any]:
    Edits = loaded["Edits"]
    SystemSettings = loaded["SystemSettings"]
    pyautogui = importlib.import_module("pyautogui")
    pyautogui.FAILSAFE = False

    main_window = pyweixin_open_main(loaded)
    current_chat = pyweixin_current_chat_name(main_window)
    if current_chat != chat_name:
        raise RuntimeError(f"current chat is not {chat_name}: {current_chat or '<empty>'}")
    edit_area = main_window.child_window(**Edits.CurrentChatEdit)
    if not edit_area.exists(timeout=0.5):
        raise RuntimeError("current chat input field is not available")
    edit_area.click_input()
    if clear:
        try:
            edit_area.set_text("")
        except Exception:  # noqa: BLE001
            pyautogui.hotkey("ctrl", "a", _pause=False)
            pyautogui.press("backspace")
            time.sleep(0.08)
    SystemSettings.copy_text_to_clipboard(text)
    pyautogui.hotkey("ctrl", "v", _pause=False)
    time.sleep(max(0.15, send_delay))

    send_button = pyweixin_find_send_button(main_window)
    send_mode = "enter"
    if send_button is not None:
        try:
            send_button.click_input()
            send_mode = "send_button"
        except Exception:  # noqa: BLE001
            pyautogui.press("enter", _pause=False)
    else:
        pyautogui.press("enter", _pause=False)

    verification = _wait_for_pyweixin_visible_text(loaded, chat_name=chat_name, text=text)
    return {
        "used_current_chat_fallback": True,
        "current_chat": chat_name,
        "input_class": edit_area.class_name(),
        "input_automation_id": edit_area.automation_id(),
        "send_mode": send_mode,
        "verified": True,
        "verification": verification,
    }


def pyweixin_open_main(loaded: dict[str, Any]) -> Any:
    Navigator = loaded["Navigator"]
    last_exc: Exception | None = None
    for attempt in range(3):
        try:
            return Navigator.open_weixin(is_maximize=False)
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if attempt < 2:
                time.sleep(0.35)
    raise RuntimeError(f"unable to open pyweixin main window: {last_exc}") from last_exc


def _is_pyweixin_transient_error(exc: BaseException) -> bool:
    name = type(exc).__name__
    text = str(exc or "")
    if (
        "无法识别定位到微信主界面" in text
        or "微信未登录" in text
        or "事件无法调用任何订户" in text
        or "unable to open dedicated dialog" in text
    ):
        return True
    return name in {"COMError", "NotFoundError", "NotLoginError"}


def pyweixin_current_chat_name(main_window: Any) -> str:
    current = main_window.child_window(
        auto_id="content_view.top_content_view.title_h_view.left_v_view.left_content_v_view.left_ui_.big_title_line_h_view.current_chat_name_label",
        control_type="Text",
    )
    if current.exists(timeout=0.3):
        return str(current.window_text() or "").strip()
    return ""


def pyweixin_go_to_session_list(main_window: Any) -> None:
    back = main_window.child_window(title="返回", control_type="Button")
    if back.exists(timeout=0.3):
        back.click_input()
        time.sleep(0.9)


def pyweixin_find_visible_session(main_window: Any, chat_name: str) -> Any | None:
    target_auto_id = f"session_item_{chat_name}"
    for item in main_window.descendants(control_type="ListItem", class_name="mmui::ChatSessionCell"):
        try:
            if item.automation_id() == target_auto_id:
                return item
            text = str(item.window_text() or "")
            if text.startswith(f"{chat_name}\n") or text == chat_name:
                return item
        except Exception:  # noqa: BLE001
            continue
    return None


def pyweixin_navigate_visible_chat(loaded: dict[str, Any], chat_name: str) -> Any:
    Navigator = loaded["Navigator"]
    main = pyweixin_open_main(loaded)
    if pyweixin_current_chat_name(main) == chat_name:
        return main
    try:
        main = Navigator.open_dialog_window(friend=chat_name, is_maximize=False, search_pages=0)
        if pyweixin_current_chat_name(main) == chat_name:
            return main
    except Exception:  # noqa: BLE001
        main = pyweixin_open_main(loaded)
    pyweixin_go_to_session_list(main)
    target = None
    main = None
    for _ in range(6):
        main = pyweixin_open_main(loaded)
        target = pyweixin_find_visible_session(main, chat_name)
        if target is not None:
            break
        time.sleep(0.35)
    if target is None or main is None:
        raise RuntimeError(f"visible session not found: {chat_name}")
    target.click_input()
    time.sleep(1.0)
    main = pyweixin_open_main(loaded)
    current_chat = pyweixin_current_chat_name(main)
    if current_chat != chat_name:
        raise RuntimeError(f"failed to switch to chat: expected {chat_name}, got {current_chat or '<empty>'}")
    return main


def open_pyweixin_dialog_local(loaded: dict[str, Any], chat_name: str, *, window_minimize: bool = True) -> Any:
    from pywinauto import Desktop

    main = pyweixin_open_main(loaded)
    pyweixin_go_to_session_list(main)
    target = pyweixin_find_visible_session(main, chat_name)
    if target is None:
        main = pyweixin_navigate_visible_chat(loaded, chat_name)
        pyweixin_go_to_session_list(main)
        target = pyweixin_find_visible_session(main, chat_name)
    if target is None:
        raise RuntimeError(f"visible session not found for dialog open: {chat_name}")

    target.double_click_input()
    desktop = Desktop(backend="uia")
    last_exc: Exception | None = None
    for _ in range(15):
        try:
            for window in desktop.windows():
                try:
                    title = str(window.window_text() or "")
                    class_name = str(window.class_name() or "")
                except Exception as exc:  # noqa: BLE001
                    last_exc = exc
                    continue
                if class_name == "mmui::ChatSingleWindow" and title == chat_name:
                    dialog = desktop.window(handle=window.handle)
                    if window_minimize:
                        try:
                            dialog.minimize()
                        except Exception:  # noqa: BLE001
                            pass
                    return dialog
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
        time.sleep(0.25)
    raise RuntimeError(f"unable to locate chat dialog window for {chat_name}: {last_exc or 'not found'}")


def pyweixin_find_message_list(main_window: Any) -> Any | None:
    for ctrl in main_window.descendants(control_type="List"):
        try:
            if ctrl.window_text() == "消息" and ctrl.class_name() == "mmui::RecyclerListView":
                return ctrl
        except Exception:  # noqa: BLE001
            continue
    return None


def serialize_list_item(item: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "text": "",
        "class_name": "",
        "automation_id": "",
        "button_texts": [],
        "text_nodes": [],
        "content_bounds": {},
    }
    try:
        payload["text"] = str(item.window_text() or "")
    except Exception:  # noqa: BLE001
        pass
    try:
        payload["class_name"] = str(item.class_name() or "")
    except Exception:  # noqa: BLE001
        pass
    try:
        payload["automation_id"] = str(getattr(item.element_info, "automation_id", "") or "")
    except Exception:  # noqa: BLE001
        pass
    try:
        payload["runtime_id"] = list(item.element_info.runtime_id)
    except Exception:  # noqa: BLE001
        payload["runtime_id"] = []
    try:
        payload["rect"] = rect_payload(item.rectangle())
    except Exception:  # noqa: BLE001
        payload["rect"] = {}

    button_texts: list[str] = []
    text_nodes: list[str] = []
    bounds: list[dict[str, int]] = []
    try:
        descendants = item.descendants()
    except Exception:  # noqa: BLE001
        descendants = []
    for descendant in descendants:
        try:
            text = str(descendant.window_text() or "").strip()
        except Exception:  # noqa: BLE001
            text = ""
        try:
            control_type = str(getattr(descendant.element_info, "control_type", "") or "")
        except Exception:  # noqa: BLE001
            control_type = ""
        if control_type == "Button" and text:
            button_texts.append(text)
        elif control_type == "Text" and text:
            text_nodes.append(text)
        if control_type in {"Button", "Text", "Image"} or text:
            try:
                bounds.append(rect_payload(descendant.rectangle()))
            except Exception:  # noqa: BLE001
                continue
    payload["button_texts"] = button_texts[:8]
    payload["text_nodes"] = text_nodes[:16]
    if bounds:
        payload["content_bounds"] = {
            "left": min(bound["left"] for bound in bounds),
            "top": min(bound["top"] for bound in bounds),
            "right": max(bound["right"] for bound in bounds),
            "bottom": max(bound["bottom"] for bound in bounds),
        }
    return payload


def classify_pyweixin_message(payload: dict[str, Any]) -> dict[str, Any]:
    text = str(payload.get("text", "") or "")
    class_name = str(payload.get("class_name", "") or "")
    kind = "unknown"
    timestamp = ""
    file_name = ""

    full_timestamp = re.search(r"(\d{4}年\d{1,2}月\d{1,2}日\s+\d{1,2}:\d{2})", text)
    short_timestamp = re.search(r"((?:星期[一二三四五六日天]|昨天|今天)\s+\d{1,2}:\d{2})", text)
    plain_time = re.fullmatch(r"\d{1,2}:\d{2}", text.strip())
    if full_timestamp:
        timestamp = full_timestamp.group(1)
    elif short_timestamp:
        timestamp = short_timestamp.group(1)
    elif plain_time:
        timestamp = plain_time.group(0)

    stripped = text.strip()
    if stripped.startswith("文件"):
        file_match = re.search(r"文件\s*\n\s*([^\n]+)", text)
        if file_match:
            file_name = file_match.group(1).strip()
            file_name = re.sub(r"\s+\d{4}年\d{1,2}月\d{1,2}日\s+\d{1,2}:\d{2}$", "", file_name).strip()
            file_name = re.sub(r"\s+(?:星期[一二三四五六日天]|昨天|今天)\s+\d{1,2}:\d{2}$", "", file_name).strip()
            file_name = re.sub(r"\s+\d{1,2}:\d{2}$", "", file_name).strip()
        kind = "file_ref"
    elif stripped.startswith("图片"):
        kind = "image_ref"
    elif stripped.startswith("视频"):
        kind = "video_ref"
    elif stripped.startswith("语音"):
        kind = "voice_ref"
    elif class_name == "mmui::ChatBubbleReferItemView":
        kind = "attachment_ref"
    elif class_name == "mmui::ChatItemView":
        kind = "timestamp"
    elif class_name == "mmui::ChatBubbleItemView" and "\n" in text:
        first_line = text.splitlines()[0].strip()
        if first_line in {"文件", "图片", "视频", "语音"}:
            kind = f"{first_line}_ref".replace("文件", "file").replace("图片", "image").replace("视频", "video").replace("语音", "voice")
        else:
            kind = "text"
    elif "Image" in class_name or text.strip().startswith("图片"):
        kind = "image_ref"
    elif class_name in {"mmui::ChatTextItemView", "mmui::ChatBubbleItemView"}:
        kind = "text"

    enriched = dict(payload)
    enriched["kind"] = kind
    enriched["timestamp"] = timestamp
    enriched["text_preview"] = text[:160]
    if file_name:
        enriched["file_name"] = file_name
    return enriched


def pyweixin_direction_from_geometry(
    payload: dict[str, Any],
    *,
    list_rect: dict[str, int] | None,
) -> tuple[str, float]:
    if not list_rect:
        return "unknown", 0.0
    bounds = payload.get("content_bounds") if isinstance(payload.get("content_bounds"), dict) else {}
    left = int(bounds.get("left", 0) or 0)
    right = int(bounds.get("right", 0) or 0)
    if left <= 0 and right <= 0:
        rect = payload.get("rect") if isinstance(payload.get("rect"), dict) else {}
        left = int(rect.get("left", 0) or 0)
        right = int(rect.get("right", 0) or 0)
    if left <= 0 and right <= 0:
        return "unknown", 0.0
    center_x = int(list_rect.get("center_x", 0) or 0)
    if center_x <= 0:
        left_edge = int(list_rect.get("left", 0) or 0)
        right_edge = int(list_rect.get("right", 0) or 0)
        if right_edge <= left_edge:
            return "unknown", 0.0
        center_x = left_edge + (right_edge - left_edge) // 2
    width = max(1, int(list_rect.get("width", 0) or 1))
    item_mid = left + max(0, right - left) // 2
    offset = item_mid - center_x
    threshold = max(32, width // 10)
    if offset >= threshold:
        return "outgoing", min(0.99, abs(offset) / width + 0.45)
    if offset <= -threshold:
        return "incoming", min(0.99, abs(offset) / width + 0.45)
    return "unknown", 0.0


def pyweixin_sender_hint(payload: dict[str, Any]) -> str:
    button_texts = [str(value).strip() for value in payload.get("button_texts", []) if str(value).strip()]
    for candidate in button_texts:
        if candidate in GENERIC_MESSAGE_LABELS:
            continue
        return candidate
    return ""


def annotate_pyweixin_message(
    payload: dict[str, Any],
    *,
    chat_name: str,
    list_rect: dict[str, int] | None = None,
) -> dict[str, Any]:
    enriched = dict(payload)
    kind = str(enriched.get("kind", "") or "")
    if kind == "timestamp":
        enriched["direction"] = "system"
        enriched["direction_confidence"] = 1.0
        enriched["is_self"] = False
        return enriched

    sender_hint = pyweixin_sender_hint(enriched)
    geometry_direction, geometry_confidence = pyweixin_direction_from_geometry(enriched, list_rect=list_rect)
    direction = geometry_direction
    confidence = geometry_confidence

    if direction == "unknown" and sender_hint:
        if sender_hint == chat_name:
            direction = "incoming"
            confidence = 0.95
        else:
            direction = "outgoing"
            confidence = 0.7

    enriched["sender_hint"] = sender_hint
    enriched["direction"] = direction
    enriched["direction_confidence"] = round(confidence, 3)
    enriched["is_self"] = direction == "outgoing"
    return enriched


def probe_pyweixin_item_direction(main_window: Any, item: Any, *, menu_items: Any) -> tuple[str, float]:
    try:
        from pywinauto import keyboard, mouse
    except ImportError:  # pragma: no cover - Windows-only helper
        return "unknown", 0.0

    try:
        rect = item.rectangle()
    except Exception:  # noqa: BLE001
        return "unknown", 0.0
    probe_x = max(int(rect.left) + 18, min(int(rect.left) + 120, int(rect.right) - 18))
    probe_y = int(rect.mid_point().y)
    mouse.right_click(coords=(probe_x, probe_y))
    time.sleep(0.08)

    menu_specs = []
    for name in ("CopyMenuItem", "SaveMenuItem", "ForwardMenuItem", "TranslateMenuItem"):
        spec = getattr(menu_items, name, None)
        if isinstance(spec, dict):
            menu_specs.append(spec)

    menu_hit = False
    try:
        for spec in menu_specs:
            candidate = main_window.child_window(**spec)
            if candidate.exists(timeout=0.08):
                menu_hit = True
                break
    finally:
        try:
            keyboard.send_keys("{ESC}")
        except Exception:  # noqa: BLE001
            pass
        time.sleep(0.05)
    if menu_hit:
        return "incoming", 0.88
    return "outgoing", 0.78


def collect_pyweixin_visible_rows(
    main_window: Any,
    msg_list: Any,
    *,
    chat_name: str,
    limit: int,
    capture_dir: str | None = None,
    menu_items: Any | None = None,
    probe_unknown_directions: bool = False,
) -> tuple[dict[str, int], list[dict[str, Any]]]:
    list_rect = rect_payload(msg_list.rectangle())
    rows: list[dict[str, Any]] = []
    output_dir = Path(capture_dir).expanduser() if capture_dir else None
    raw_items = msg_list.children(control_type="ListItem")[:limit]
    for index, item in enumerate(raw_items, start=1):
        payload = annotate_pyweixin_message(
            classify_pyweixin_message(serialize_list_item(item)),
            chat_name=chat_name,
            list_rect=list_rect,
        )
        if probe_unknown_directions and payload.get("kind") != "timestamp" and str(payload.get("direction", "")) == "unknown" and menu_items is not None:
            direction, confidence = probe_pyweixin_item_direction(main_window, item, menu_items=menu_items)
            payload["direction"] = direction
            payload["direction_confidence"] = confidence
            payload["is_self"] = direction == "outgoing"
        if output_dir is not None and payload["kind"] in {"image_ref", "attachment_ref", "file_ref", "video_ref", "voice_ref"}:
            filename = f"{index:03d}_{payload['kind']}_{safe_stem(chat_name)}.png"
            try:
                payload["capture_path"] = capture_list_item_image(item, output_dir / filename)
            except Exception as exc:  # noqa: BLE001
                payload["capture_error"] = str(exc)
        rows.append(payload)
    return list_rect, rows


def safe_stem(value: str) -> str:
    cleaned = re.sub(r"[^0-9A-Za-z._-]+", "_", value.strip())
    return cleaned.strip("._") or "item"


def normalize_chat_text(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())


def dedupe_preserve_order(values: list[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for raw in values:
        item = str(raw or "").strip()
        if not item or item in seen:
            continue
        seen.add(item)
        deduped.append(item)
    return deduped


def capture_list_item_image(item: Any, output_path: Path) -> str:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    pyautogui = importlib.import_module("pyautogui")
    rect = item.rectangle()
    left = max(0, int(rect.left))
    top = max(0, int(rect.top))
    width = max(1, int(rect.right - rect.left))
    height = max(1, int(rect.bottom - rect.top))
    screenshot = pyautogui.screenshot(region=(left, top, width, height))
    screenshot.save(str(output_path))
    return str(output_path)


def read_pyweixin_visible_messages(
    loaded: dict[str, Any],
    chat_name: str,
    limit: int = 20,
    *,
    capture_dir: str | None = None,
) -> dict[str, Any]:
    main = pyweixin_navigate_visible_chat(loaded, chat_name)
    return _pyweixin_visible_messages_from_main(
        loaded,
        main,
        chat_name=chat_name,
        limit=limit,
        capture_dir=capture_dir,
    )


def pyweixin_open_history_window(loaded: dict[str, Any], chat_name: str) -> Any:
    from pywinauto import Desktop

    Navigator = loaded["Navigator"]
    try:
        history_window = Navigator.open_chat_history(friend=chat_name, search_pages=0, is_maximize=False, close_weixin=False)
        return history_window
    except Exception:  # noqa: BLE001
        pass

    main = pyweixin_navigate_visible_chat(loaded, chat_name)
    desktop = Desktop(backend="uia")

    def find_history_window() -> Any | None:
        for window in desktop.windows():
            try:
                title = str(window.window_text() or "")
                class_name = str(window.class_name() or "")
                if class_name == "mmui::SearchMsgUniqueChatWindow":
                    return desktop.window(handle=window.handle)
                if "聊天记录" in title:
                    return desktop.window(handle=window.handle)
            except Exception:  # noqa: BLE001
                continue
        return None

    existing = find_history_window()
    if existing is not None:
        return existing

    button = main.child_window(title="聊天记录", control_type="Button")
    if not button.exists(timeout=0.5):
        raise RuntimeError("history button not found")
    button.click_input()
    for _ in range(12):
        time.sleep(0.3)
        history = find_history_window()
        if history is not None:
            return history
    raise RuntimeError("history window not found")


def read_pyweixin_history_messages(
    loaded: dict[str, Any],
    chat_name: str,
    *,
    limit: int = 20,
    page_turns: int = 0,
    capture_dir: str | None = None,
) -> dict[str, Any]:
    from pywinauto import mouse

    history_window = pyweixin_open_history_window(loaded, chat_name)
    history_list = None
    for ctrl in history_window.descendants(control_type="List"):
        history_list = ctrl
        break
    if history_list is None:
        raise RuntimeError("history list not found")

    rect = history_list.rectangle()
    list_rect = rect_payload(rect)
    mouse.click(coords=(rect.mid_point().x, rect.mid_point().y))
    time.sleep(0.2)

    seen: set[tuple[int, ...]] = set()
    rows: list[dict[str, Any]] = []
    output_dir = Path(capture_dir).expanduser() if capture_dir else None

    def collect() -> None:
        for item in history_list.children(control_type="ListItem"):
            payload = annotate_pyweixin_message(
                classify_pyweixin_message(serialize_list_item(item)),
                chat_name=chat_name,
                list_rect=list_rect,
            )
            runtime = tuple(int(value) for value in payload.get("runtime_id", []) if isinstance(value, int))
            marker = runtime or (hash(payload["text"]),)
            if marker in seen:
                continue
            seen.add(marker)
            if output_dir is not None and payload["kind"] in {"image_ref", "attachment_ref", "file_ref", "video_ref", "voice_ref"}:
                filename = f"{len(rows)+1:03d}_{payload['kind']}_{safe_stem(chat_name)}.png"
                try:
                    payload["capture_path"] = capture_list_item_image(item, output_dir / filename)
                except Exception as exc:  # noqa: BLE001
                    payload["capture_error"] = str(exc)
            rows.append(payload)

    collect()
    for _ in range(max(0, int(page_turns))):
        if len(rows) >= limit:
            break
        history_list.type_keys("{PGDN}")
        time.sleep(0.8)
        collect()

    try:
        history_window.close()
    except Exception:  # noqa: BLE001
        pass

    return {
        "chat_name": chat_name,
        "list_rect": list_rect,
        "message_count": min(len(rows), limit),
        "messages": rows[:limit],
    }


def normalize_history_row(row: dict[str, Any]) -> dict[str, Any]:
    payload = dict(row)
    payload["kind"] = str(payload.get("kind", "") or "unknown")
    payload["timestamp"] = str(payload.get("timestamp", "") or "")
    payload["text"] = str(payload.get("text", "") or "")
    payload["text_preview"] = str(payload.get("text_preview", payload["text"]) or "")
    payload["file_name"] = str(payload.get("file_name", "") or "")
    payload["capture_path"] = str(payload.get("capture_path", "") or "")
    return payload


def history_row_digest(chat_name: str, row: dict[str, Any]) -> str:
    payload = normalize_history_row(row)
    seed = "\n".join(
        [
            chat_name,
            payload["kind"],
            payload["timestamp"],
            payload["text"],
            payload["file_name"],
            payload["capture_path"],
        ]
    )
    return hashlib.sha1(seed.encode("utf-8")).hexdigest()[:16]


def history_row_identity(chat_name: str, row: dict[str, Any]) -> str:
    payload = normalize_history_row(row)
    seed = "\n".join(
        [
            chat_name,
            payload["kind"],
            payload["timestamp"],
            payload["text"],
            payload["file_name"],
        ]
    )
    return hashlib.sha1(seed.encode("utf-8")).hexdigest()[:16]


def visible_row_digest(chat_name: str, row: dict[str, Any]) -> str:
    payload = normalize_history_row(row)
    seed = "\n".join(
        [
            chat_name,
            payload["kind"],
            payload["text"],
            payload["file_name"],
        ]
    )
    return hashlib.sha1(seed.encode("utf-8")).hexdigest()[:24]


def pick_latest_visible_item(messages: list[dict[str, Any]]) -> dict[str, Any] | None:
    fallback_item: dict[str, Any] | None = None
    unknown_item: dict[str, Any] | None = None
    for item in reversed(messages):
        kind = str(item.get("kind", "") or "")
        text = normalize_chat_text(str(item.get("text", "") or ""))
        if not text or kind == "timestamp":
            continue
        if fallback_item is None:
            fallback_item = item
        is_self = bool(item.get("is_self", False))
        direction = str(item.get("direction", "") or "")
        if not is_self and direction == "incoming":
            return item
        if unknown_item is None and not is_self and direction not in {"outgoing", "system"}:
            unknown_item = item
    return unknown_item or fallback_item


def build_turn_from_visible_item(
    *,
    chat_name: str,
    item: dict[str, Any],
    unread_count: int,
    source_ref: str,
    dialog_mode: bool = False,
) -> ChatTurn:
    kind = str(item.get("kind", ""))
    text = normalize_chat_text(str(item.get("text", "") or ""))
    timestamp = str(item.get("timestamp", "")).strip()
    message_id = hashlib.sha1(f"{chat_name}\n{timestamp}\n{text}".encode("utf-8")).hexdigest()[:24]
    metadata = {
        "unread_count": max(1, int(unread_count)),
        "pyweixin_kind": kind,
        "visible_timestamp": timestamp,
        "capture_path": str(item.get("capture_path", "") or ""),
        "file_name": str(item.get("file_name", "") or ""),
        "direction": str(item.get("direction", "") or ""),
        "direction_confidence": float(item.get("direction_confidence", 0.0) or 0.0),
        "is_self": bool(item.get("is_self", False)),
        "sender_hint": str(item.get("sender_hint", "") or ""),
        "visible_digest": visible_row_digest(chat_name, item),
    }
    if dialog_mode:
        metadata["dialog_mode"] = True
    return ChatTurn(
        chat_name=chat_name,
        sender=str(item.get("sender_hint", "") or chat_name),
        text=text,
        channel="wechat",
        is_group=False,
        mentioned=False,
        message_id=message_id,
        thread_key=chat_name,
        ts=int(time.time()),
        source_ref=source_ref,
        metadata=metadata,
    )


def is_recent_outbound_echo(turn: ChatTurn, *, state: StateStore, now: float, max_age_seconds: int = 150) -> bool:
    visible_digest = str(turn.metadata.get("visible_digest", "") or "").strip()
    direction = str(turn.metadata.get("direction", "") or "")
    confidence = float(turn.metadata.get("direction_confidence", 0.0) or 0.0)
    row = state.last_outbound(turn.chat_name)
    if not row:
        return False
    digests = set(state.outbound_digests(turn.chat_name))
    if visible_digest and visible_digest in digests:
        return True
    sent_at = int(row.get("sent_at", 0) or 0)
    if sent_at and (now - sent_at) > max_age_seconds:
        return False
    bubble_texts = [normalize_chat_text(part) for part in row.get("bubble_texts", []) if normalize_chat_text(part)]
    if not bubble_texts:
        fallback_text = normalize_chat_text(str(row.get("text", "") or ""))
        bubble_texts = [fallback_text] if fallback_text else []
    current_text = normalize_chat_text(turn.text)
    if not current_text or not bubble_texts:
        return False
    if current_text not in bubble_texts:
        return False
    if direction == "outgoing":
        return True
    if direction == "incoming" and confidence >= 0.7:
        return False
    return True


def dedupe_history_rows(chat_name: str, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        marker = history_row_digest(chat_name, row)
        if marker in seen:
            continue
        seen.add(marker)
        deduped.append(normalize_history_row(row))
    return deduped


def history_payload_digest(chat_name: str, rows: list[dict[str, Any]]) -> str:
    tokens = [history_row_identity(chat_name, row) for row in rows]
    seed = "\n".join(tokens)
    return hashlib.sha1(seed.encode("utf-8")).hexdigest()[:20]


def render_history_markdown(chat_name: str, rows: list[dict[str, Any]]) -> str:
    lines = [f"# Weixin History Export: {chat_name}", "", "这是一份从 Windows Weixin 读取出来的可见聊天历史导出。", ""]
    for index, row in enumerate(rows, start=1):
        payload = normalize_history_row(row)
        lines.append(f"## {index}. {payload['kind']}")
        if payload["timestamp"]:
            lines.append(f"- timestamp: {payload['timestamp']}")
        if payload["file_name"]:
            lines.append(f"- file_name: {payload['file_name']}")
        if payload["capture_path"]:
            lines.append(f"- capture_path: {payload['capture_path']}")
        body = payload["text"].strip() or payload["text_preview"].strip()
        if body:
            lines.append("- content:")
            lines.append(body)
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def history_export_path(config: HelperConfig, chat_name: str) -> Path:
    export_dir = config.receipt_dir / "history_exports"
    export_dir.mkdir(parents=True, exist_ok=True)
    return export_dir / f"{current_stamp()}_{safe_stem(chat_name)}_history.md"


def export_history_markdown(config: HelperConfig, chat_name: str, rows: list[dict[str, Any]]) -> Path:
    digest = history_payload_digest(chat_name, rows)
    export_dir = config.receipt_dir / "history_exports"
    export_dir.mkdir(parents=True, exist_ok=True)
    path = export_dir / f"{current_stamp()}_{safe_stem(chat_name)}_{digest}_history.md"
    atomic_write_text(path, render_history_markdown(chat_name, rows))
    return path


def artifact_note_for_history(chat_name: str, row: dict[str, Any], *, source: str) -> str:
    payload = normalize_history_row(row)
    pieces = [f"来源聊天：{chat_name}", f"来源：{source}", f"条目类型：{payload['kind']}"]
    if payload["timestamp"]:
        pieces.append(f"时间：{payload['timestamp']}")
    if payload["file_name"]:
        pieces.append(f"文件名：{payload['file_name']}")
    return "，".join(pieces) + "。"


def sync_history_payload_to_memory(
    config: HelperConfig,
    client: AgentClient,
    *,
    chat_name: str,
    payload: dict[str, Any],
    state: StateStore | None = None,
    include_captures: bool = True,
    dry_run: bool = False,
    force: bool = False,
) -> dict[str, Any]:
    rows = dedupe_history_rows(chat_name, list(payload.get("messages", [])))
    digest = history_payload_digest(chat_name, rows)
    if state is not None and not force and state.last_history_sync_digest(chat_name) == digest:
        return {
            "chat_name": chat_name,
            "message_count": len(rows),
            "status": "skipped_duplicate_history",
            "history_digest": digest,
            "capture_reports": [],
        }
    export_path = export_history_markdown(config, chat_name, rows)
    export_report = client.ingest_artifact(
        {
            "path": str(export_path),
            "note": f"这是来自微信聊天 {chat_name} 的历史导出。",
            "tags": ["wechat_history", "chat_export", safe_stem(chat_name)],
            "dry_run": dry_run,
            "source": "windows_helper.pyweixin.history_export",
        }
    )

    capture_reports: list[dict[str, Any]] = []
    if include_captures:
        for row in rows:
            capture_path = str(row.get("capture_path", "") or "").strip()
            if not capture_path:
                continue
            capture_reports.append(
                client.ingest_artifact(
                    {
                        "path": capture_path,
                        "note": artifact_note_for_history(chat_name, row, source="windows_helper.pyweixin.history_capture"),
                        "tags": ["wechat_history_capture", safe_stem(chat_name), str(row.get("kind", ""))],
                        "dry_run": dry_run,
                        "source": "windows_helper.pyweixin.history_capture",
                    }
                )
            )

    if state is not None and not dry_run:
        state.mark_history_synced(chat_name, digest=digest, export_path=str(export_path))

    return {
        "chat_name": chat_name,
        "message_count": len(rows),
        "status": "ingested",
        "history_digest": digest,
        "export_path": str(export_path),
        "export_report": export_report,
        "capture_reports": capture_reports,
    }


def parse_pyweixin_session_unread(automation_id: str, text: str) -> tuple[str, int] | None:
    unread_match = re.search(r"\[(\d+)条\]", str(text or ""))
    if unread_match is None:
        return None
    try:
        unread_count = int(unread_match.group(1))
    except Exception:  # noqa: BLE001
        return None
    chat_name = str(automation_id or "").replace("session_item_", "").strip()
    if not chat_name:
        first_line = str(text or "").splitlines()[0].strip()
        chat_name = re.sub(r"\s*\[\d+条\]\s*$", "", first_line).strip()
    if not chat_name:
        return None
    if "消息免打扰" in str(text or ""):
        return None
    if chat_name in {"服务号", "公众号"}:
        return None
    return chat_name, max(1, unread_count)


def visible_pyweixin_unread_map(loaded: dict[str, Any]) -> dict[str, int]:
    try:
        main = pyweixin_open_main(loaded)
    except Exception:  # noqa: BLE001
        return {}
    sidebar = loaded.get("SideBar")
    if sidebar is not None:
        try:
            chats_button = main.child_window(**getattr(sidebar, "Weixin"))
            if chats_button.exists(timeout=0.2):
                chats_button.click_input()
                time.sleep(0.25)
                main = pyweixin_open_main(loaded)
        except Exception:  # noqa: BLE001
            pass
    rows: dict[str, int] = {}
    for item in main.descendants(control_type="ListItem", class_name="mmui::ChatSessionCell"):
        try:
            automation_id = str(item.automation_id() or "")
        except Exception:  # noqa: BLE001
            automation_id = ""
        try:
            text = str(item.window_text() or "")
        except Exception:  # noqa: BLE001
            text = ""
        parsed = parse_pyweixin_session_unread(automation_id, text)
        if parsed is None:
            continue
        chat_name, unread_count = parsed
        rows[chat_name] = unread_count
    return rows


def scan_pyweixin_new_messages(loaded: dict[str, Any]) -> dict[str, int]:
    utils_mod = loaded["utils"]
    normalized: dict[str, int] = {}
    try:
        result = utils_mod.scan_for_new_messages(is_maximize=False, close_weixin=False)
    except Exception:  # noqa: BLE001
        result = None
    if isinstance(result, dict):
        for chat_name, unread in result.items():
            label = str(chat_name or "").strip()
            if not label:
                continue
            try:
                normalized[label] = int(unread)
            except Exception:  # noqa: BLE001
                normalized[label] = 1
    if normalized:
        return normalized
    try:
        return visible_pyweixin_unread_map(loaded)
    except Exception:  # noqa: BLE001
        return {}


def passive_pyweixin_turns(
    loaded: dict[str, Any],
    *,
    chat_names: list[str],
    capture_root: Path,
) -> list[ChatTurn]:
    turns: list[ChatTurn] = []
    for chat_name in chat_names:
        label = str(chat_name or "").strip()
        if not label:
            continue
        try:
            turn = latest_pyweixin_turn(
                loaded,
                chat_name=label,
                unread_count=1,
                capture_dir=str(capture_root / safe_stem(label)),
            )
        except Exception:  # noqa: BLE001
            continue
        if turn is None or bool(turn.metadata.get("is_self", False)):
            continue
        turns.append(turn)
    return turns


def latest_pyweixin_turn(
    loaded: dict[str, Any],
    *,
    chat_name: str,
    unread_count: int = 1,
    capture_dir: str | None = None,
) -> ChatTurn | None:
    if "Navigator" in loaded:
        main = pyweixin_navigate_visible_chat(loaded, chat_name)
        msg_list = pyweixin_find_message_list(main)
        if msg_list is None:
            raise RuntimeError("message list not found in current chat")
        _list_rect, messages = collect_pyweixin_visible_rows(
            main,
            msg_list,
            chat_name=chat_name,
            limit=40,
            capture_dir=capture_dir,
            menu_items=loaded.get("MenuItems"),
            probe_unknown_directions=False,
        )
    else:
        payload = read_pyweixin_visible_messages(loaded, chat_name, limit=40, capture_dir=capture_dir)
        messages = list(payload.get("messages", []))
    selected_item = pick_latest_visible_item(messages)
    if selected_item is None:
        return None
    return build_turn_from_visible_item(
        chat_name=chat_name,
        item=selected_item,
        unread_count=unread_count,
        source_ref=f"pyweixin:{chat_name}",
    )


def latest_pyweixin_dialog_turn(
    loaded: dict[str, Any],
    *,
    dialog_window: Any,
    chat_name: str,
    unread_count: int = 1,
    capture_dir: str | None = None,
) -> ChatTurn | None:
    msg_list = pyweixin_find_message_list(dialog_window)
    if msg_list is None:
        raise RuntimeError("message list not found in dedicated dialog")
    _list_rect, messages = collect_pyweixin_visible_rows(
        dialog_window,
        msg_list,
        chat_name=chat_name,
        limit=40,
        capture_dir=capture_dir,
        menu_items=loaded.get("MenuItems"),
        probe_unknown_directions=False,
    )
    selected_item = pick_latest_visible_item(messages)
    if selected_item is None:
        return None
    return build_turn_from_visible_item(
        chat_name=chat_name,
        item=selected_item,
        unread_count=unread_count,
        source_ref=f"pyweixin_dialog:{chat_name}",
        dialog_mode=True,
    )


def queue_send_task(config: HelperConfig, *, chat_name: str, text: str, search: str | None = None, task_id: str = "") -> dict[str, Any]:
    config.send_queue_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "task_id": task_id or hashlib.sha1(f"{chat_name}\n{text}\n{time.time()}".encode("utf-8")).hexdigest()[:16],
        "chat_name": chat_name,
        "search": (search or chat_name).strip(),
        "text": text,
        "created_at": int(time.time()),
        "process_path": config.pywinauto_process_path,
    }
    path = config.send_queue_dir / f"{payload['task_id']}.json"
    atomic_write_text(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    return {"queued": True, "task": payload, "path": str(path)}


def live_capture_dir(config: HelperConfig, chat_name: str) -> Path:
    path = config.receipt_dir / "live_captures" / safe_stem(chat_name)
    path.mkdir(parents=True, exist_ok=True)
    return path


def maybe_ingest_turn_artifact(
    turn: ChatTurn,
    *,
    client: AgentClient,
    dry_run: bool = False,
) -> dict[str, Any] | None:
    metadata = dict(turn.metadata or {})
    kind = str(metadata.get("pyweixin_kind", "") or "")
    capture_path = str(metadata.get("capture_path", "") or "").strip()
    if kind not in RICH_MEDIA_KINDS or not capture_path:
        return None
    note_parts = [f"来源聊天：{turn.chat_name}", f"条目类型：{kind}"]
    timestamp = str(metadata.get("visible_timestamp", "") or "").strip()
    if timestamp:
        note_parts.append(f"时间：{timestamp}")
    file_name = str(metadata.get("file_name", "") or "").strip()
    if file_name:
        note_parts.append(f"文件名：{file_name}")
    return client.ingest_artifact(
        {
            "path": capture_path,
            "note": "，".join(note_parts) + "。",
            "tags": ["wechat_live_capture", safe_stem(turn.chat_name), kind],
            "dry_run": dry_run,
            "source": "windows_helper.pyweixin.live_capture",
        }
    )


def is_paused(config: HelperConfig) -> bool:
    return config.pause_file.exists()


def whitelisted(config: HelperConfig, turn: ChatTurn) -> bool:
    if not config.whitelist:
        return True
    return turn.chat_name in set(config.whitelist)


def process_one_turn(
    turn: ChatTurn,
    *,
    client: AgentClient,
    state: StateStore,
    adapter: Any,
    config: HelperConfig,
) -> dict[str, Any]:
    now = time.time()
    if bool(turn.metadata.get("is_self", False)):
        state.remember(turn)
        return {"action": "ignore", "reason": "self_message", "chat_name": turn.chat_name}
    if is_recent_outbound_echo(turn, state=state, now=now):
        state.remember(turn)
        return {"action": "ignore", "reason": "outbound_echo", "chat_name": turn.chat_name}
    if not whitelisted(config, turn):
        state.remember(turn)
        return {"action": "ignore", "reason": "not_whitelisted", "chat_name": turn.chat_name}
    if not state.can_send(turn.chat_name, now=now, cooldown_seconds=config.cooldown_seconds):
        return {"action": "ignore", "reason": "cooldown", "chat_name": turn.chat_name}

    reply = client.reply(turn)
    if reply.get("action") != "reply" or not str(reply.get("text", "")).strip():
        if str(reply.get("reason", "") or "") not in {"throttled_contact", "codex_failure"}:
            state.remember(turn)
        return reply
    reply_text = str(reply["text"]).strip()
    bubbles = [str(part).strip() for part in reply.get("bubbles", []) if str(part).strip()]
    if not bubbles:
        bubbles = [reply_text]
    cadence_ms = []
    if isinstance(reply.get("cadence_ms"), list):
        cadence_ms = [int(part) for part in reply.get("cadence_ms", []) if isinstance(part, (int, float))]
    if hasattr(adapter, "send_bubbles"):
        send_record = adapter.send_bubbles(turn, bubbles, cadence_ms=cadence_ms, draft_only=config.draft_only)
    else:
        send_record = adapter.send_reply(turn, reply_text, draft_only=config.draft_only)
    send_result = send_record.get("send_result") if isinstance(send_record, dict) else None
    if not config.draft_only and isinstance(send_result, dict) and not bool(send_result.get("ok", False)):
        return {
            "action": "ignore",
            "reason": "send_failed",
            "chat_name": turn.chat_name,
            "send_result": send_result,
        }
    state.remember(turn)
    state.mark_sent(turn.chat_name, now=now)
    state.remember_outbound(
        turn.chat_name,
        text=" ".join(bubbles),
        digest=hashlib.sha1(f"{turn.chat_name}\ntext\n{' '.join(bubbles)}\n".encode("utf-8")).hexdigest()[:24],
        bubbles=bubbles,
        now=now,
    )
    return reply


def command_health(config_path: str | None) -> int:
    config = load_config(config_path)
    client = AgentClient(config.agent_url, timeout_seconds=config.timeout_seconds)
    print_json(client.health())
    return 0


def command_send_turn(config_path: str | None, payload: dict[str, Any]) -> int:
    config = load_config(config_path)
    client = AgentClient(config.agent_url, timeout_seconds=config.timeout_seconds)
    print_json(client.reply(parse_turn(payload)))
    return 0


def command_queue_send(config_path: str | None, *, chat_name: str, text: str, search: str | None = None, task_id: str = "") -> int:
    config = load_config(config_path)
    print_json(queue_send_task(config, chat_name=chat_name, text=text, search=search, task_id=task_id))
    return 0


def command_snapshot(config_path: str | None, payload: dict[str, Any]) -> int:
    config = load_config(config_path)
    client = AgentClient(config.agent_url, timeout_seconds=config.timeout_seconds)
    print_json(client.snapshot(payload))
    return 0


def command_restore_snapshot(config_path: str | None, payload: dict[str, Any]) -> int:
    config = load_config(config_path)
    client = AgentClient(config.agent_url, timeout_seconds=config.timeout_seconds)
    print_json(client.restore_snapshot(payload))
    return 0


def command_revive_packet(config_path: str | None, *, path: str | None, query: str | None) -> int:
    config = load_config(config_path)
    client = AgentClient(config.agent_url, timeout_seconds=config.timeout_seconds)
    print_json(client.revive_packet(path=path, query=query))
    return 0


def command_watch_inbox(config_path: str | None, *, once: bool = False) -> int:
    config = load_config(config_path)
    client = AgentClient(config.agent_url, timeout_seconds=config.timeout_seconds)
    adapter = JsonInboxAdapter(config)
    state = StateStore(config.state_file)

    while True:
        if is_paused(config):
            time.sleep(config.poll_seconds)
            if once:
                break
            continue
        for turn, source in adapter.poll_turns(limit=10):
            try:
                if state.already_seen(turn):
                    adapter.mark_processed(source)
                    continue
                result = process_one_turn(turn, client=client, state=state, adapter=adapter, config=config)
                state.save()
                adapter.mark_processed(source)
                print_json({"turn": turn.to_payload(), "result": result})
            except Exception as exc:  # noqa: BLE001
                state.save()
                print_json(
                    {
                        "turn": turn.to_payload(),
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                        "source": str(source),
                    }
                )
        if once:
            break
        time.sleep(config.poll_seconds)
    return 0


def command_wcf_contacts(config_path: str | None, *, needle: str | None = None, limit: int = 20) -> int:
    config = load_config(config_path)
    adapter = WcfAdapter(config)
    try:
        matches = adapter.list_contacts(needle=needle, limit=limit)
        payload = {
            "self_wxid": adapter.self_wxid(),
            "matches": matches,
            "match_count": len(matches),
        }
        print_json(payload)
    finally:
        adapter.close()
    return 0


def command_wcf_info(config_path: str | None) -> int:
    config = load_config(config_path)
    print_json(wcf_runtime_info(config))
    return 0


def command_watch_wcf(config_path: str | None, *, once: bool = False, max_messages: int = 0) -> int:
    config = load_config(config_path)
    client = AgentClient(config.agent_url, timeout_seconds=config.timeout_seconds)
    adapter = WcfAdapter(config)
    state = StateStore(config.state_file)
    handled = 0

    try:
        write_transport_state(
            config,
            status="starting",
            mode="live",
            transport="wcf",
            detail="attaching wcf transport",
        )
        adapter.start_receiving()
        write_transport_state(
            config,
            status="online",
            mode="live",
            transport="wcf",
            detail="receiving messages",
            extra={"self_wxid": adapter.self_wxid()},
        )
        while True:
            if is_paused(config):
                write_transport_state(
                    config,
                    status="paused",
                    mode="live",
                    transport="wcf",
                    detail="pause file present",
                    heartbeat_only=True,
                )
                time.sleep(config.poll_seconds)
                if once:
                    break
                continue
            try:
                turn = adapter.next_turn()
            except Empty:
                write_transport_state(
                    config,
                    status="online",
                    mode="live",
                    transport="wcf",
                    detail="idle",
                    heartbeat_only=True,
                )
                if once:
                    break
                continue
            if turn is None:
                write_transport_state(
                    config,
                    status="online",
                    mode="live",
                    transport="wcf",
                    detail="filtered non-text event",
                    heartbeat_only=True,
                )
                continue
            try:
                if state.already_seen(turn):
                    write_transport_state(
                        config,
                        status="online",
                        mode="live",
                        transport="wcf",
                        detail="duplicate skipped",
                        heartbeat_only=True,
                        extra={"last_chat_name": turn.chat_name},
                    )
                    continue
                result = process_one_turn(turn, client=client, state=state, adapter=adapter, config=config)
                state.save()
                write_transport_state(
                    config,
                    status="online",
                    mode="live",
                    transport="wcf",
                    detail="turn handled",
                    heartbeat_only=True,
                    extra={"last_chat_name": turn.chat_name, "last_result": str(result.get("action", ""))},
                )
                print_json({"turn": turn.to_payload(), "result": result})
                handled += 1
            except Exception as exc:  # noqa: BLE001
                state.save()
                write_transport_state(
                    config,
                    status="degraded",
                    mode="live",
                    transport="wcf",
                    detail=str(exc),
                    error_type=type(exc).__name__,
                    extra={"last_chat_name": turn.chat_name},
                )
                print_json({"turn": turn.to_payload(), "error_type": type(exc).__name__, "error": str(exc)})
            if once and handled >= 1:
                break
            if max_messages > 0 and handled >= max_messages:
                break
    finally:
        state.save()
        adapter.close()
        write_transport_state(
            config,
            status="stopped",
            mode="live",
            transport="wcf",
            detail="watch loop exited",
        )
    return 0


def command_watch_live(config_path: str | None, *, once: bool = False, max_messages: int = 0) -> int:
    config = load_config(config_path)
    mode = (config.watch_mode or "auto").strip().lower()
    errors: list[str] = []

    if mode in {"wcf", "auto"}:
        try:
            return command_watch_wcf(config_path, once=once, max_messages=max_messages)
        except Exception as exc:  # noqa: BLE001
            write_transport_state(
                config,
                status="degraded",
                mode="live",
                transport="wcf",
                detail=str(exc),
                error_type=type(exc).__name__,
            )
            errors.append(f"wcf:{type(exc).__name__}:{exc}")
            if mode == "wcf" or not config.allow_transport_fallback:
                raise

    if mode in {"pyweixin", "auto"}:
        try:
            return command_watch_pyweixin(config_path, once=once, max_messages=max_messages)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"pyweixin:{type(exc).__name__}:{exc}")
            raise RuntimeError("; ".join(errors)) from exc

    if mode in {"pyweixin_dialog"}:
        return command_watch_pyweixin_dialog(config_path, once=once, max_messages=max_messages)

    raise RuntimeError(f"unknown watch_mode: {mode}")


def command_watch_pyweixin(config_path: str | None, *, once: bool = False, max_messages: int = 0) -> int:
    config = load_config(config_path)
    client = AgentClient(config.agent_url, timeout_seconds=config.timeout_seconds)
    adapter = PyweixinReplyAdapter(config)
    state = StateStore(config.state_file)
    loaded = import_pyweixin(config.pyweixin_repo_path)
    handled = 0
    seen_unread = 0
    last_passive_probe_at = 0.0
    write_transport_state(
        config,
        status="starting",
        mode="maintenance",
        transport="pyweixin",
        detail="starting maintenance watcher",
    )

    while True:
        if is_paused(config):
            write_transport_state(
                config,
                status="paused",
                mode="maintenance",
                transport="pyweixin",
                detail="pause file present",
                heartbeat_only=True,
            )
            if once:
                print_json({"handled": handled, "status": "paused"})
            time.sleep(config.poll_seconds)
            if once:
                break
            continue

        try:
            unread = scan_pyweixin_new_messages(loaded)
        except Exception as exc:  # noqa: BLE001
            write_transport_state(
                config,
                status="degraded",
                mode="maintenance",
                transport="pyweixin",
                detail=str(exc),
                error_type=type(exc).__name__,
            )
            print_json(
                {
                    "handled": handled,
                    "status": "scan_error",
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                }
            )
            state.save()
            loaded = import_pyweixin(config.pyweixin_repo_path)
            if once:
                return 1
            time.sleep(max(config.poll_seconds, 1.0))
            continue
        turns_to_process: list[tuple[ChatTurn, int, str]] = []
        for chat_name, unread_count in unread.items():
            probe_turn = ChatTurn(chat_name=chat_name, text="", sender=chat_name, channel="wechat", thread_key=chat_name)
            if not whitelisted(config, probe_turn):
                continue
            try:
                turn = latest_pyweixin_turn(
                    loaded,
                    chat_name=chat_name,
                    unread_count=unread_count,
                    capture_dir=str(live_capture_dir(config, chat_name)),
                )
            except Exception as exc:  # noqa: BLE001
                print_json(
                    {
                        "chat_name": chat_name,
                        "unread_count": unread_count,
                        "status": "turn_probe_error",
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                    }
                )
                continue
            if turn is None:
                continue
            turns_to_process.append((turn, unread_count, "unread"))
        if not turns_to_process and config.whitelist and config.passive_probe_enabled:
            now = time.time()
            allow_passive = (now - last_passive_probe_at) >= max(config.passive_probe_interval_seconds, 1.0)
            if allow_passive and config.passive_probe_requires_foreground:
                allow_passive = pyweixin_is_foreground(config.pywinauto_process_path)
            if allow_passive:
                last_passive_probe_at = now
                try:
                    passive = passive_pyweixin_turns(
                        loaded,
                        chat_names=list(config.whitelist),
                        capture_root=config.receipt_dir / "live_captures",
                    )
                except Exception as exc:  # noqa: BLE001
                    print_json(
                        {
                            "status": "passive_probe_error",
                            "error_type": type(exc).__name__,
                            "error": str(exc),
                        }
                    )
                    passive = []
            else:
                passive = []
            for turn in passive:
                turns_to_process.append((turn, 1, "passive"))
        if not turns_to_process:
            write_transport_state(
                config,
                status="online",
                mode="maintenance",
                transport="pyweixin",
                detail="idle",
                heartbeat_only=True,
            )
            if once:
                print_json({"handled": handled, "status": "no_unread"})
            if once:
                break
            time.sleep(config.poll_seconds)
            continue
        seen_unread += len(unread)

        for turn, unread_count, trigger_mode in turns_to_process:
            try:
                if state.already_seen(turn):
                    continue
                result = process_one_turn(turn, client=client, state=state, adapter=adapter, config=config)
                artifact_report = None
                artifact_error = None
                try:
                    artifact_report = maybe_ingest_turn_artifact(turn, client=client, dry_run=False)
                except Exception as exc:  # noqa: BLE001
                    artifact_error = {"error_type": type(exc).__name__, "error": str(exc)}
                state.save()
                write_transport_state(
                    config,
                    status="online",
                    mode="maintenance",
                    transport="pyweixin",
                    detail="turn handled",
                    heartbeat_only=True,
                    extra={"last_chat_name": turn.chat_name, "last_result": str(result.get("action", ""))},
                )
                print_json(
                    {
                        "turn": turn.to_payload(),
                        "result": result,
                        "unread_count": unread_count,
                        "trigger_mode": trigger_mode,
                        "artifact_report": artifact_report,
                        "artifact_error": artifact_error,
                    }
                )
                handled += 1
            except Exception as exc:  # noqa: BLE001
                state.save()
                write_transport_state(
                    config,
                    status="degraded",
                    mode="maintenance",
                    transport="pyweixin",
                    detail=str(exc),
                    error_type=type(exc).__name__,
                    extra={"last_chat_name": turn.chat_name},
                )
                print_json(
                    {
                        "turn": turn.to_payload(),
                        "unread_count": unread_count,
                        "trigger_mode": trigger_mode,
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                    }
                )
            if once and handled >= 1:
                return 0
            if max_messages > 0 and handled >= max_messages:
                return 0

        if once:
            print_json({"handled": handled, "status": "scanned", "unread_chats": seen_unread})
            break
        time.sleep(config.poll_seconds)

    state.save()
    write_transport_state(
        config,
        status="stopped",
        mode="maintenance",
        transport="pyweixin",
        detail="watch loop exited",
    )
    return 0


def _poll_duration_string(seconds: float) -> str:
    whole = max(1, int(round(seconds)))
    return f"{whole}s"


def _dialog_turn_from_text(chat_name: str, text: str) -> ChatTurn:
    clean_text = str(text or "").strip()
    digest = hashlib.sha1(f"{chat_name}\ntext\n{clean_text}\n".encode("utf-8")).hexdigest()[:24]
    now = int(time.time())
    return ChatTurn(
        chat_name=chat_name,
        text=clean_text,
        sender=chat_name,
        channel="wechat",
        is_group=False,
        mentioned=False,
        message_id=f"pyweixin-dialog-{digest}-{now}",
        thread_key=chat_name,
        ts=now,
        source_ref=f"pyweixin_dialog:{chat_name}",
        metadata={
            "pyweixin_kind": "text",
            "dialog_mode": True,
            "visible_digest": digest,
            "direction": "unknown",
            "direction_confidence": 0.0,
            "is_self": False,
            "sender_hint": chat_name,
        },
    )


def command_watch_pyweixin_dialog(config_path: str | None, *, once: bool = False, max_messages: int = 0) -> int:
    config = load_config(config_path)
    if not config.whitelist:
        raise RuntimeError("pyweixin_dialog mode requires at least one whitelisted chat")
    client = AgentClient(config.agent_url, timeout_seconds=config.timeout_seconds)
    state = StateStore(config.state_file)
    loaded = import_pyweixin(config.pyweixin_repo_path)
    adapter = PyweixinDialogAdapter(config, loaded)
    handled = 0
    write_transport_state(
        config,
        status="starting",
        mode="live",
        transport="pyweixin_dialog",
        detail="opening dedicated dialog windows",
        extra={"watch_chats": list(config.whitelist)},
    )
    try:
        online_announced = False
        while True:
            if is_paused(config):
                write_transport_state(
                    config,
                    status="paused",
                    mode="live",
                    transport="pyweixin_dialog",
                    detail="pause file present",
                    heartbeat_only=True,
                )
                time.sleep(config.poll_seconds)
                if once:
                    break
                continue
            saw_message = False
            dialog_ready = False
            transient_errors: list[str] = []
            for chat_name in config.whitelist:
                try:
                    dialog = adapter.ensure_dialog(chat_name)
                    dialog_ready = True
                    turn = latest_pyweixin_dialog_turn(
                        loaded,
                        dialog_window=dialog,
                        chat_name=chat_name,
                        unread_count=1,
                        capture_dir=str(live_capture_dir(config, chat_name)),
                    )
                    if turn is None or state.already_seen(turn):
                        continue
                    result = process_one_turn(turn, client=client, state=state, adapter=adapter, config=config)
                    state.save()
                    saw_message = True
                    handled += 1
                    write_transport_state(
                        config,
                        status="online",
                        mode="live",
                        transport="pyweixin_dialog",
                        detail="turn handled",
                        heartbeat_only=True,
                        extra={"last_chat_name": turn.chat_name, "last_result": str(result.get("action", ""))},
                    )
                    print_json({"turn": turn.to_payload(), "result": result, "source": "pyweixin_dialog"})
                    if once and handled >= 1:
                        return 0
                    if max_messages > 0 and handled >= max_messages:
                        return 0
                except Exception as exc:  # noqa: BLE001
                    state.save()
                    if _is_pyweixin_transient_error(exc):
                        transient_errors.append(f"{chat_name}:{type(exc).__name__}:{exc}")
                        continue
                    write_transport_state(
                        config,
                        status="degraded",
                        mode="live",
                        transport="pyweixin_dialog",
                        detail=str(exc),
                        error_type=type(exc).__name__,
                        extra={"last_chat_name": chat_name},
                    )
                    print_json(
                        {
                            "chat_name": chat_name,
                            "source": "pyweixin_dialog",
                            "error_type": type(exc).__name__,
                            "error": str(exc),
                        }
                    )
                    raise
            if dialog_ready:
                detail = "turn handled" if saw_message else "polling dedicated dialog windows"
                extra: dict[str, Any] = {"watch_chats": list(config.whitelist)}
                if saw_message:
                    extra["handled"] = handled
                write_transport_state(
                    config,
                    status="online",
                    mode="live",
                    transport="pyweixin_dialog",
                    detail=detail,
                    heartbeat_only=online_announced,
                    extra=extra,
                )
                online_announced = True
            elif transient_errors:
                write_transport_state(
                    config,
                    status="degraded",
                    mode="live",
                    transport="pyweixin_dialog",
                    detail="; ".join(transient_errors[:2]),
                    error_type="TransientPyweixinError",
                    extra={"watch_chats": list(config.whitelist)},
                )
            if once:
                status = "degraded" if transient_errors and not dialog_ready else "scanned"
                print_json({"handled": handled, "status": status, "watch_chats": list(config.whitelist)})
                break
            if dialog_ready and not saw_message:
                write_transport_state(
                    config,
                    status="online",
                    mode="live",
                    transport="pyweixin_dialog",
                    detail="idle",
                    heartbeat_only=True,
                )
    finally:
        state.save()
        adapter.close()
        write_transport_state(
            config,
            status="stopped",
            mode="live",
            transport="pyweixin_dialog",
            detail="watch loop exited",
        )
    return 0


def command_probe_wechat(process_path: str) -> int:
    try:
        from pywinauto import Application
        import win32api
        import win32con
        import win32gui
        import win32process
    except ImportError as exc:  # pragma: no cover - Windows-only helper
        raise SystemExit("pywinauto is required for probe-wechat; install it on Windows first.") from exc

    chosen = locate_wechat_window(
        process_path,
        Application=Application,
        win32api=win32api,
        win32con=win32con,
        win32gui=win32gui,
        win32process=win32process,
    )
    print(json.dumps({"chosen_window": chosen}, ensure_ascii=False, indent=2))
    app = Application(backend="uia").connect(handle=int(chosen["hwnd"]))
    window = app.window(handle=int(chosen["hwnd"]))
    window.print_control_identifiers()
    return 0


def locate_wechat_window(
    process_path: str,
    *,
    Application: Any,
    win32api: Any,
    win32con: Any,
    win32gui: Any,
    win32process: Any,
) -> dict[str, Any]:
    target_path = os.path.normcase(process_path)
    target_name = os.path.basename(target_path)
    candidates: list[dict[str, Any]] = []

    def process_path_for_hwnd(hwnd: int) -> str:
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        access = win32con.PROCESS_QUERY_LIMITED_INFORMATION | win32con.PROCESS_VM_READ
        handle = None
        try:
            handle = win32api.OpenProcess(access, False, pid)
            return os.path.normcase(win32process.GetModuleFileNameEx(handle, 0))
        except Exception:  # noqa: BLE001
            return ""
        finally:
            if handle:
                win32api.CloseHandle(handle)

    def cb(hwnd: int, _extra: Any) -> None:
        if not win32gui.IsWindowVisible(hwnd):
            return
        title = win32gui.GetWindowText(hwnd).strip()
        if not title:
            return
        real_path = process_path_for_hwnd(hwnd)
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        if real_path == target_path or os.path.basename(real_path) == target_name or "weixin" in title.lower() or "微信" in title:
            candidates.append({"hwnd": hwnd, "pid": pid, "title": title, "path": real_path})

    win32gui.EnumWindows(cb, None)
    if not candidates:
        raise SystemExit(f"No visible WeChat/Weixin window found for {process_path}")

    candidates.sort(key=lambda item: (item["path"] != target_path, item["title"]))
    chosen = candidates[0]
    chosen["candidate_count"] = len(candidates)
    return chosen


def pyweixin_is_foreground(process_path: str) -> bool:
    try:
        import win32api
        import win32con
        import win32gui
        import win32process
    except ImportError:
        return False

    hwnd = win32gui.GetForegroundWindow()
    if not hwnd:
        return False
    try:
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        access = win32con.PROCESS_QUERY_LIMITED_INFORMATION | win32con.PROCESS_VM_READ
        handle = win32api.OpenProcess(access, False, pid)
        try:
            resolved = os.path.normcase(win32process.GetModuleFileNameEx(handle, 0))
        finally:
            try:
                win32api.CloseHandle(handle)
            except Exception:  # noqa: BLE001
                pass
    except Exception:  # noqa: BLE001
        return False
    return resolved == os.path.normcase(process_path)


def command_scan_wechat_text(process_path: str, needle: str | None = None, limit: int = 80) -> int:
    try:
        from pywinauto import Application
        import win32api
        import win32con
        import win32gui
        import win32process
    except ImportError as exc:  # pragma: no cover - Windows-only helper
        raise SystemExit("pywinauto is required for scan-wechat-text; install it on Windows first.") from exc

    chosen = locate_wechat_window(
        process_path,
        Application=Application,
        win32api=win32api,
        win32con=win32con,
        win32gui=win32gui,
        win32process=win32process,
    )
    app = Application(backend="uia").connect(handle=int(chosen["hwnd"]))
    window = app.window(handle=int(chosen["hwnd"]))
    lowered_needle = needle.lower() if needle else ""
    items: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for elem in window.descendants():
        try:
            text = (elem.window_text() or "").strip()
            control_type = str(elem.element_info.control_type or "")
            if not text:
                continue
            key = (text, control_type)
            if key in seen:
                continue
            if lowered_needle and lowered_needle not in text.lower():
                continue
            seen.add(key)
            items.append(
                {
                    "text": text,
                    "control_type": control_type,
                    "automation_id": str(getattr(elem.element_info, "automation_id", "") or ""),
                    "class_name": str(getattr(elem.element_info, "class_name", "") or ""),
                }
            )
        except Exception:  # noqa: BLE001
            continue
    payload = {"chosen_window": chosen, "matches": items[:limit], "match_count": len(items)}
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def command_probe_pyweixin(config_path: str | None) -> int:
    config = load_config(config_path)
    print_json(probe_pyweixin_state(config))
    return 0


def prime_pyweixin_runtime(
    config: HelperConfig,
    *,
    restart_weixin: bool = False,
    wait_seconds: float = 0.0,
) -> dict[str, Any]:
    narrator_path = Path(os.environ.get("WINDIR", r"C:\Windows")) / "System32" / "Narrator.exe"
    actions: list[dict[str, Any]] = []

    if narrator_path.exists():
        try:
            subprocess.Popen([str(narrator_path)], close_fds=True)
            actions.append({"step": "start_narrator", "path": str(narrator_path), "ok": True, "method": "exe"})
        except OSError as exc:
            shortcut_payload = {
                "step": "start_narrator",
                "path": str(narrator_path),
                "ok": False,
                "method": "exe",
                "error_type": type(exc).__name__,
                "error": str(exc),
            }
            if getattr(exc, "winerror", 0) == 740:
                try:
                    import pyautogui

                    pyautogui.FAILSAFE = False
                    pyautogui.hotkey("winleft", "ctrl", "enter")
                    shortcut_payload = {
                        "step": "start_narrator",
                        "path": str(narrator_path),
                        "ok": True,
                        "method": "hotkey",
                        "hotkey": "Win+Ctrl+Enter",
                    }
                except Exception as hotkey_exc:  # noqa: BLE001
                    shortcut_payload["hotkey_error_type"] = type(hotkey_exc).__name__
                    shortcut_payload["hotkey_error"] = str(hotkey_exc)
            actions.append(shortcut_payload)
    else:
        actions.append({"step": "start_narrator", "path": str(narrator_path), "ok": False})

    if restart_weixin:
        process_path = str(config.pywinauto_process_path or "").strip()
        image_name = os.path.basename(process_path) or "Weixin.exe"
        kill = subprocess.run(
            ["taskkill", "/F", "/IM", image_name],
            capture_output=True,
            text=True,
            encoding="gbk",
            errors="replace",
            check=False,
        )
        actions.append(
            {
                "step": "taskkill_weixin",
                "image_name": image_name,
                "returncode": int(kill.returncode),
                "stdout": (kill.stdout or "").strip(),
                "stderr": (kill.stderr or "").strip(),
            }
        )
        time.sleep(1.2)
        if process_path and Path(process_path).exists():
            subprocess.Popen([process_path], close_fds=True)
            actions.append({"step": "restart_weixin", "path": process_path, "ok": True})
        else:
            actions.append({"step": "restart_weixin", "path": process_path, "ok": False})

    if wait_seconds > 0:
        time.sleep(wait_seconds)
        actions.append({"step": "wait", "seconds": wait_seconds})

    return {"ok": True, "actions": actions}


def command_prime_pyweixin(
    config_path: str | None,
    *,
    restart_weixin: bool = False,
    wait_seconds: float = 0.0,
) -> int:
    config = load_config(config_path)
    print_json(prime_pyweixin_runtime(config, restart_weixin=restart_weixin, wait_seconds=wait_seconds))
    return 0


def send_via_pyweixin(
    config: HelperConfig,
    *,
    chat_name: str,
    text: str,
    search_pages: int = 0,
    clear: bool = True,
    send_delay: float = 0.25,
) -> dict[str, Any]:
    loaded = import_pyweixin(config.pyweixin_repo_path)
    GlobalConfig = loaded["GlobalConfig"]

    GlobalConfig.close_weixin = False
    GlobalConfig.is_maximize = False
    GlobalConfig.clear = clear
    GlobalConfig.search_pages = int(search_pages)
    GlobalConfig.send_delay = float(send_delay)

    payload: dict[str, Any] = {
        "repo_path": loaded["repo_path"],
        "chat_name": chat_name,
        "text": text,
        "search_pages": int(search_pages),
        "send_delay": float(send_delay),
    }
    try:
        main = pyweixin_navigate_visible_chat(loaded, chat_name)
        current_chat = pyweixin_current_chat_name(main)
        payload["resolved_chat"] = current_chat
        if current_chat != chat_name:
            raise RuntimeError(f"refusing to send: expected current chat {chat_name}, got {current_chat or '<empty>'}")
        payload["send_mode"] = "current_chat_only"
        payload["send_result"] = send_current_chat_via_pyweixin(
            loaded=loaded,
            chat_name=chat_name,
            text=text,
            clear=clear,
            send_delay=send_delay,
        )
        payload["ok"] = True
    except Exception as exc:  # noqa: BLE001
        payload["error_type"] = type(exc).__name__
        payload["error"] = str(exc)
        probe = probe_pyweixin_state(config)
        payload["probe"] = probe
        payload["ok"] = False
    return payload


def command_send_pyweixin(
    config_path: str | None,
    *,
    chat_name: str,
    text: str,
    search_pages: int = 0,
    clear: bool = True,
    send_delay: float = 0.25,
) -> int:
    config = load_config(config_path)
    payload = send_via_pyweixin(
        config,
        chat_name=chat_name,
        text=text,
        search_pages=search_pages,
        clear=clear,
        send_delay=send_delay,
    )
    print_json(payload)
    return 0


def command_read_pyweixin_visible(
    config_path: str | None,
    *,
    chat_name: str,
    limit: int = 20,
    capture_dir: str | None = None,
) -> int:
    config = load_config(config_path)
    loaded = import_pyweixin(config.pyweixin_repo_path)
    payload = read_pyweixin_visible_messages(loaded, chat_name, limit=max(1, limit), capture_dir=capture_dir)
    print_json(payload)
    return 0


def command_read_pyweixin_history(
    config_path: str | None,
    *,
    chat_name: str,
    limit: int = 20,
    page_turns: int = 0,
    capture_dir: str | None = None,
) -> int:
    config = load_config(config_path)
    loaded = import_pyweixin(config.pyweixin_repo_path)
    payload = read_pyweixin_history_messages(
        loaded,
        chat_name,
        limit=max(1, limit),
        page_turns=max(0, page_turns),
        capture_dir=capture_dir,
    )
    print_json(payload)
    return 0


def command_ingest_pyweixin_history(
    config_path: str | None,
    *,
    chat_name: str,
    limit: int = 20,
    page_turns: int = 0,
    capture_dir: str | None = None,
    include_visible: bool = True,
    include_captures: bool = True,
    dry_run: bool = False,
    force: bool = False,
) -> int:
    config = load_config(config_path)
    client = AgentClient(config.agent_url, timeout_seconds=config.timeout_seconds)
    state = StateStore(config.state_file)
    loaded = import_pyweixin(config.pyweixin_repo_path)
    resolved_capture_dir = capture_dir
    if include_captures and not resolved_capture_dir:
        resolved_capture_dir = str((config.receipt_dir / "history_captures" / safe_stem(chat_name)).resolve())

    rows: list[dict[str, Any]] = []
    if include_visible:
        visible_payload = read_pyweixin_visible_messages(
            loaded,
            chat_name,
            limit=max(1, min(limit, 30)),
            capture_dir=resolved_capture_dir,
        )
        rows.extend(list(visible_payload.get("messages", [])))

    history_payload = read_pyweixin_history_messages(
        loaded,
        chat_name,
        limit=max(1, limit),
        page_turns=max(0, page_turns),
        capture_dir=resolved_capture_dir,
    )
    rows.extend(list(history_payload.get("messages", [])))

    report = sync_history_payload_to_memory(
        config,
        client,
        chat_name=chat_name,
        payload={"messages": rows},
        state=state,
        include_captures=include_captures,
        dry_run=dry_run,
        force=force,
    )
    if not dry_run:
        state.save()
    report["capture_dir"] = resolved_capture_dir or ""
    report["include_visible"] = include_visible
    report["include_captures"] = include_captures
    report["page_turns"] = page_turns
    print_json(report)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Windows helper shim for the Holo WSL host")
    parser.add_argument("--config", default=None, help="Path to wechat_helper.json")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("health", help="Ping the WSL Holo reply API")

    send_parser = subparsers.add_parser("send-turn", help="Send one explicit chat turn to the WSL reply API")
    send_parser.add_argument("--chat-name", required=True)
    send_parser.add_argument("--text", required=True)
    send_parser.add_argument("--sender", default="")
    send_parser.add_argument("--channel", default="wechat")
    send_parser.add_argument("--message-id", default="")
    send_parser.add_argument("--thread-key", default="")
    send_parser.add_argument("--ts", type=int, default=None)
    send_parser.add_argument("--group", action="store_true")
    send_parser.add_argument("--mentioned", action="store_true")

    queue_parser = subparsers.add_parser("queue-send", help="Queue one Weixin send task for the detached Windows sender")
    queue_parser.add_argument("--chat-name", required=True)
    queue_parser.add_argument("--text", required=True)
    queue_parser.add_argument("--search", default=None)
    queue_parser.add_argument("--task-id", default="")

    watch_parser = subparsers.add_parser("watch-inbox", help="Process JSON inbox events and forward them to the WSL reply API")
    watch_parser.add_argument("--once", action="store_true")

    subparsers.add_parser("wcf-info", help="Report local wcferry and WeChat/Weixin compatibility")
    contacts_parser = subparsers.add_parser("wcf-contacts", help="List or search contacts through wcferry")
    contacts_parser.add_argument("--needle", default=None)
    contacts_parser.add_argument("--limit", type=int, default=20)

    wcf_watch_parser = subparsers.add_parser("watch-wcf", help="Receive live WeChat messages through wcferry and forward them to the WSL reply API")
    wcf_watch_parser.add_argument("--once", action="store_true")
    wcf_watch_parser.add_argument("--max-messages", type=int, default=0)
    live_watch_parser = subparsers.add_parser("watch-live", help="Run the preferred live watcher (WCF-first, optional pyweixin fallback)")
    live_watch_parser.add_argument("--once", action="store_true")
    live_watch_parser.add_argument("--max-messages", type=int, default=0)

    pyweixin_dialog_parser = subparsers.add_parser("watch-pyweixin-dialog", help="Listen on dedicated minimized pyweixin dialog windows for whitelisted chats")
    pyweixin_dialog_parser.add_argument("--once", action="store_true")
    pyweixin_dialog_parser.add_argument("--max-messages", type=int, default=0)
    pyweixin_watch_parser = subparsers.add_parser("watch-pyweixin", help="Poll unread Weixin chats via pyweixin and forward whitelisted turns to the WSL reply API")
    pyweixin_watch_parser.add_argument("--once", action="store_true")
    pyweixin_watch_parser.add_argument("--max-messages", type=int, default=0)

    snapshot_parser = subparsers.add_parser("snapshot", help="Ask the WSL host to write a portable snapshot")
    snapshot_parser.add_argument("--path", default=None)
    snapshot_parser.add_argument("--label", default=None)
    snapshot_parser.add_argument("--query", default=None)

    restore_parser = subparsers.add_parser("restore-snapshot", help="Ask the WSL host to restore a saved snapshot")
    restore_parser.add_argument("--path", required=True)
    restore_parser.add_argument("--mode", choices=("merge", "replace"), default="merge")
    restore_parser.add_argument("--dry-run", action="store_true")
    restore_parser.add_argument("--restore-persona-files", action="store_true")

    revive_parser = subparsers.add_parser("revive-packet", help="Ask the WSL host for a revive packet")
    revive_parser.add_argument("--path", default=None)
    revive_parser.add_argument("--query", default=None)
    artifact_parser = subparsers.add_parser("ingest-artifact", help="Ask the WSL host to ingest one local file into Holo memory")
    artifact_parser.add_argument("--path", required=True)
    artifact_parser.add_argument("--note", default=None)
    artifact_parser.add_argument("--tags", nargs="*", default=[])
    artifact_parser.add_argument("--dry-run", action="store_true")

    probe_parser = subparsers.add_parser("probe-wechat", help="Print a pywinauto control tree for the running WeChat window")
    probe_parser.add_argument("--process-path", default=None)
    scan_parser = subparsers.add_parser("scan-wechat-text", help="Scan visible WeChat UI text and optionally filter it")
    scan_parser.add_argument("--process-path", default=None)
    scan_parser.add_argument("--needle", default=None)
    scan_parser.add_argument("--limit", type=int, default=80)
    subparsers.add_parser("probe-pyweixin", help="Probe whether the 4.1+ pyweixin path can see the live Weixin UI")
    prime_parser = subparsers.add_parser("prime-pyweixin", help="Launch Narrator and optionally restart Weixin for pyweixin probing")
    prime_parser.add_argument("--restart-weixin", action="store_true")
    prime_parser.add_argument("--wait-seconds", type=float, default=0.0)
    send_pyweixin_parser = subparsers.add_parser("send-pyweixin", help="Attempt a direct 4.1+ pyweixin send to one contact")
    send_pyweixin_parser.add_argument("--chat-name", required=True)
    send_pyweixin_parser.add_argument("--text", required=True)
    send_pyweixin_parser.add_argument("--search-pages", type=int, default=0)
    send_pyweixin_parser.add_argument("--send-delay", type=float, default=0.25)
    send_pyweixin_parser.add_argument("--no-clear", action="store_true")
    read_visible_parser = subparsers.add_parser("read-pyweixin-visible", help="Read visible messages from a visible chat via pyweixin")
    read_visible_parser.add_argument("--chat-name", required=True)
    read_visible_parser.add_argument("--limit", type=int, default=20)
    read_visible_parser.add_argument("--capture-dir", default=None)
    read_history_parser = subparsers.add_parser("read-pyweixin-history", help="Read farther history via the pyweixin chat-history window")
    read_history_parser.add_argument("--chat-name", required=True)
    read_history_parser.add_argument("--limit", type=int, default=20)
    read_history_parser.add_argument("--page-turns", type=int, default=0)
    read_history_parser.add_argument("--capture-dir", default=None)
    ingest_history_parser = subparsers.add_parser("ingest-pyweixin-history", help="Read Weixin chat history and ingest it into Holo memory")
    ingest_history_parser.add_argument("--chat-name", required=True)
    ingest_history_parser.add_argument("--limit", type=int, default=20)
    ingest_history_parser.add_argument("--page-turns", type=int, default=0)
    ingest_history_parser.add_argument("--capture-dir", default=None)
    ingest_history_parser.add_argument("--no-visible", action="store_true")
    ingest_history_parser.add_argument("--no-captures", action="store_true")
    ingest_history_parser.add_argument("--dry-run", action="store_true")
    ingest_history_parser.add_argument("--force", action="store_true")

    args = parser.parse_args(argv)

    if args.command == "health":
        return command_health(args.config)
    if args.command == "send-turn":
        return command_send_turn(
            args.config,
            {
                "chat_name": args.chat_name,
                "text": args.text,
                "sender": args.sender,
                "channel": args.channel,
                "message_id": args.message_id,
                "thread_key": args.thread_key,
                "ts": args.ts,
                "is_group": args.group,
                "mentioned": args.mentioned,
            },
        )
    if args.command == "queue-send":
        return command_queue_send(args.config, chat_name=args.chat_name, text=args.text, search=args.search, task_id=args.task_id)
    if args.command == "watch-inbox":
        return command_watch_inbox(args.config, once=args.once)
    if args.command == "wcf-info":
        return command_wcf_info(args.config)
    if args.command == "wcf-contacts":
        return command_wcf_contacts(args.config, needle=args.needle, limit=args.limit)
    if args.command == "watch-wcf":
        return command_watch_wcf(args.config, once=args.once, max_messages=args.max_messages)
    if args.command == "watch-live":
        return command_watch_live(args.config, once=args.once, max_messages=args.max_messages)
    if args.command == "watch-pyweixin-dialog":
        return command_watch_pyweixin_dialog(args.config, once=args.once, max_messages=args.max_messages)
    if args.command == "watch-pyweixin":
        return command_watch_pyweixin(args.config, once=args.once, max_messages=args.max_messages)
    if args.command == "snapshot":
        return command_snapshot(
            args.config,
            {"path": args.path, "label": args.label, "query": args.query},
        )
    if args.command == "restore-snapshot":
        return command_restore_snapshot(
            args.config,
            {
                "path": args.path,
                "mode": args.mode,
                "dry_run": args.dry_run,
                "restore_persona_files": args.restore_persona_files,
            },
        )
    if args.command == "revive-packet":
        return command_revive_packet(args.config, path=args.path, query=args.query)
    if args.command == "ingest-artifact":
        config = load_config(args.config)
        client = AgentClient(config.agent_url, timeout_seconds=config.timeout_seconds)
        print_json(
            client.ingest_artifact(
                {
                    "path": args.path,
                    "note": args.note,
                    "tags": args.tags,
                    "dry_run": args.dry_run,
                    "source": "windows_helper.manual_artifact",
                }
            )
        )
        return 0
    if args.command == "probe-wechat":
        config = load_config(args.config)
        return command_probe_wechat(args.process_path or config.pywinauto_process_path)
    if args.command == "scan-wechat-text":
        config = load_config(args.config)
        return command_scan_wechat_text(
            args.process_path or config.pywinauto_process_path,
            needle=args.needle,
            limit=args.limit,
        )
    if args.command == "probe-pyweixin":
        return command_probe_pyweixin(args.config)
    if args.command == "prime-pyweixin":
        return command_prime_pyweixin(
            args.config,
            restart_weixin=args.restart_weixin,
            wait_seconds=args.wait_seconds,
        )
    if args.command == "send-pyweixin":
        return command_send_pyweixin(
            args.config,
            chat_name=args.chat_name,
            text=args.text,
            search_pages=args.search_pages,
            clear=not args.no_clear,
            send_delay=args.send_delay,
        )
    if args.command == "read-pyweixin-visible":
        return command_read_pyweixin_visible(
            args.config,
            chat_name=args.chat_name,
            limit=args.limit,
            capture_dir=args.capture_dir,
        )
    if args.command == "read-pyweixin-history":
        return command_read_pyweixin_history(
            args.config,
            chat_name=args.chat_name,
            limit=args.limit,
            page_turns=args.page_turns,
            capture_dir=args.capture_dir,
        )
    if args.command == "ingest-pyweixin-history":
        return command_ingest_pyweixin_history(
            args.config,
            chat_name=args.chat_name,
            limit=args.limit,
            page_turns=args.page_turns,
            capture_dir=args.capture_dir,
            include_visible=not args.no_visible,
            include_captures=not args.no_captures,
            dry_run=args.dry_run,
            force=args.force,
        )
    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
