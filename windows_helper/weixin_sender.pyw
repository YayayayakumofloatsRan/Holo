from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from wechat_helper import HelperConfig, load_config, send_via_pyweixin
from weixin_debug import bring_front, capture_window, click_window, foreground_info, list_visible_windows, locate_window, maybe_search_and_send


def ensure_dirs(config: HelperConfig) -> None:
    for path in (config.send_queue_dir, config.sent_dir, config.failed_dir, config.receipt_dir):
        path.mkdir(parents=True, exist_ok=True)


def load_task(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def move_task(source: Path, target_dir: Path) -> Path:
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / source.name
    source.replace(target)
    return target


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f".{path.name}.tmp-{int(time.time() * 1000)}")
    try:
        temp_path.write_text(text, encoding="utf-8")
        temp_path.replace(path)
    finally:
        if temp_path.exists():
            temp_path.unlink(missing_ok=True)


def write_receipt(config: HelperConfig, task: dict, payload: dict) -> Path:
    config.receipt_dir.mkdir(parents=True, exist_ok=True)
    receipt = config.receipt_dir / f"{task['task_id']}.json"
    atomic_write_text(receipt, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    return receipt


def fail_task(config: HelperConfig, task_path: Path, task: dict, payload: dict) -> dict:
    failed_path = move_task(task_path, config.failed_dir)
    payload = dict(payload)
    payload["task"] = task
    payload["task_path"] = str(failed_path)
    write_receipt(config, {"task_id": str(task.get("task_id", task_path.stem))}, payload)
    return payload


def send_one(config: HelperConfig, task_path: Path) -> dict:
    task = load_task(task_path)
    task_id = str(task.get("task_id", task_path.stem))
    process_path = str(task.get("process_path") or config.pywinauto_process_path)
    search = str(task.get("search") or task.get("chat_name") or "").strip()
    text = str(task.get("text") or "").strip()
    if not search or not text:
        return fail_task(config, task_path, task, {"ok": False, "reason": "missing_search_or_text"})

    if config.pyweixin_repo_path:
        pyweixin_result = send_via_pyweixin(config, chat_name=search, text=text, search_pages=0, clear=True, send_delay=0.25)
        if pyweixin_result.get("ok"):
            sent_path = move_task(task_path, config.sent_dir)
            payload = {
                "ok": True,
                "transport": "pyweixin",
                "task": task,
                "task_path": str(sent_path),
                "result": pyweixin_result,
            }
            write_receipt(config, {"task_id": task_id}, payload)
            return payload
        return fail_task(
            config,
            task_path,
            task,
            {
                "ok": False,
                "reason": "pyweixin_send_failed",
                "transport": "pyweixin",
                "result": pyweixin_result,
            },
        )

    chosen = locate_window(process_path)
    hwnd = int(chosen["hwnd"])
    bring_front(hwnd, chosen.get("title", ""))
    time.sleep(0.8)
    focus_click = click_window(hwnd)
    time.sleep(0.3)
    before_path = config.receipt_dir / f"{task_id}-before.png"
    before_capture = capture_window(hwnd, before_path)
    interaction = maybe_search_and_send(hwnd, search, text, 0.8)
    try:
        current = locate_window(process_path)
    except Exception as exc:  # noqa: BLE001
        return fail_task(
            config,
            task_path,
            task,
            {
                "ok": False,
                "reason": "post_interaction_window_missing",
                "error": str(exc),
                "chosen_window": chosen,
                "foreground": foreground_info(),
                "focus_click": {"x": focus_click[0], "y": focus_click[1]},
                "before_capture": before_capture,
                "interaction": interaction,
                "visible_windows_after": list_visible_windows(process_path, include_empty_titles=True),
            },
        )
    snap_path = config.receipt_dir / f"{task_id}.png"
    capture = capture_window(int(current["hwnd"]), snap_path)
    foreground = foreground_info()
    sent_path = move_task(task_path, config.sent_dir)
    payload = {
        "ok": True,
        "task": task,
        "task_path": str(sent_path),
        "chosen_window": chosen,
        "current_window": current,
        "foreground": foreground,
        "focus_click": {"x": focus_click[0], "y": focus_click[1]},
        "before_capture": before_capture,
        "interaction": interaction,
        "capture": capture,
    }
    write_receipt(config, {"task_id": task_id}, payload)
    return payload


def run_once(config: HelperConfig) -> int:
    ensure_dirs(config)
    pending = sorted(config.send_queue_dir.glob("*.json"))
    if not pending:
        return 0
    try:
        send_one(config, pending[0])
    except Exception as exc:  # noqa: BLE001
        task = load_task(pending[0])
        fail_task(config, pending[0], task, {"ok": False, "reason": "exception", "error": str(exc)})
    return 0


def run_loop(config: HelperConfig, *, poll_seconds: float) -> int:
    ensure_dirs(config)
    while True:
        pending = sorted(config.send_queue_dir.glob("*.json"))
        if pending:
            try:
                send_one(config, pending[0])
            except Exception as exc:  # noqa: BLE001
                task = load_task(pending[0])
                failed_path = move_task(pending[0], config.failed_dir)
                write_receipt(
                    config,
                    {"task_id": str(task.get("task_id", pending[0].stem))},
                    {"ok": False, "reason": "exception", "error": str(exc), "task": task, "task_path": str(failed_path)},
                )
        time.sleep(poll_seconds)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Detached Windows-side sender for Weixin tasks")
    parser.add_argument("--config", default=None)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--poll-seconds", type=float, default=1.0)
    args = parser.parse_args(argv)

    config = load_config(args.config)
    if args.once:
        return run_once(config)
    return run_loop(config, poll_seconds=args.poll_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
