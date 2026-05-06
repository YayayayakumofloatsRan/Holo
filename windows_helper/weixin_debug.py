from __future__ import annotations

import argparse
import json
import time
from pathlib import Path


def list_visible_windows(process_path: str, *, include_empty_titles: bool = False) -> list[dict]:
    import os
    import win32api
    import win32con
    import win32gui
    import win32process

    target_path = os.path.normcase(process_path)
    target_name = os.path.basename(target_path)
    candidates: list[dict] = []

    def _path_for_hwnd(hwnd: int) -> str:
        _tid, pid = win32process.GetWindowThreadProcessId(hwnd)
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

    def cb(hwnd: int, _extra) -> None:
        if not win32gui.IsWindowVisible(hwnd):
            return
        title = win32gui.GetWindowText(hwnd).strip()
        if not title and not include_empty_titles:
            return
        real_path = _path_for_hwnd(hwnd)
        _tid, pid = win32process.GetWindowThreadProcessId(hwnd)
        if real_path == target_path or target_name == Path(real_path).name or "weixin" in title.lower() or "微信" in title:
            left, top, right, bottom = win32gui.GetWindowRect(hwnd)
            candidates.append(
                {
                    "hwnd": hwnd,
                    "pid": pid,
                    "title": title,
                    "path": real_path,
                    "class_name": win32gui.GetClassName(hwnd),
                    "rect": {"left": left, "top": top, "right": right, "bottom": bottom},
                }
            )

    win32gui.EnumWindows(cb, None)
    return candidates


def locate_window(process_path: str) -> dict:
    import os

    target_path = os.path.normcase(process_path)
    candidates = list_visible_windows(process_path)
    if not candidates:
        raise RuntimeError(f"No visible Weixin window found for {process_path}")
    def area(item: dict) -> int:
        rect = item.get("rect", {})
        return max(0, int(rect.get("right", 0)) - int(rect.get("left", 0))) * max(
            0, int(rect.get("bottom", 0)) - int(rect.get("top", 0))
        )
    candidates.sort(key=lambda item: (item["path"] != target_path, -area(item), item["title"]))
    chosen = candidates[0]
    chosen["candidate_count"] = len(candidates)
    return chosen


def process_path_for_hwnd(hwnd: int) -> str:
    import os
    import win32api
    import win32con
    import win32process

    _tid, pid = win32process.GetWindowThreadProcessId(hwnd)
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


def foreground_info() -> dict:
    import win32gui

    hwnd = int(win32gui.GetForegroundWindow())
    return {
        "hwnd": hwnd,
        "title": win32gui.GetWindowText(hwnd).strip(),
        "class_name": win32gui.GetClassName(hwnd),
        "path": process_path_for_hwnd(hwnd),
    }


def bring_front(hwnd: int, title: str = "") -> None:
    import win32com.client
    import win32con
    import win32gui

    shell = win32com.client.Dispatch("WScript.Shell")
    if title:
        try:
            shell.AppActivate(title)
            time.sleep(0.2)
        except Exception:  # noqa: BLE001
            pass
    shell.SendKeys("%")
    win32gui.ShowWindow(hwnd, win32con.SW_SHOWNORMAL)
    win32gui.BringWindowToTop(hwnd)
    win32gui.SetWindowPos(hwnd, win32con.HWND_TOPMOST, 0, 0, 0, 0, win32con.SWP_NOMOVE | win32con.SWP_NOSIZE)
    win32gui.SetWindowPos(hwnd, win32con.HWND_NOTOPMOST, 0, 0, 0, 0, win32con.SWP_NOMOVE | win32con.SWP_NOSIZE)
    win32gui.SetForegroundWindow(hwnd)


def click_window(hwnd: int, *, x_ratio: float = 0.08, y_ratio: float = 0.08) -> tuple[int, int]:
    import pyautogui
    import win32gui

    left, top, right, bottom = win32gui.GetWindowRect(hwnd)
    x = int(left + (right - left) * x_ratio)
    y = int(top + (bottom - top) * y_ratio)
    pyautogui.click(x=x, y=y)
    return x, y


def click_relative(hwnd: int, *, x_ratio: float, y_ratio: float, clicks: int = 1, interval: float = 0.0) -> tuple[int, int]:
    import pyautogui
    import win32gui

    left, top, right, bottom = win32gui.GetWindowRect(hwnd)
    x = int(left + (right - left) * x_ratio)
    y = int(top + (bottom - top) * y_ratio)
    pyautogui.click(x=x, y=y, clicks=clicks, interval=interval)
    return x, y


def capture_window(hwnd: int, output: Path) -> dict:
    import win32gui
    from PIL import ImageGrab

    left, top, right, bottom = win32gui.GetWindowRect(hwnd)
    image = ImageGrab.grab(bbox=(left, top, right, bottom), all_screens=True)
    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output)
    return {"output": str(output), "width": int(right - left), "height": int(bottom - top)}


def maybe_search_and_send(hwnd: int, search: str | None, message: str | None, delay: float) -> dict[str, dict[str, int]]:
    import pyautogui
    import pyperclip

    points: dict[str, dict[str, int]] = {}

    if search:
        x, y = click_relative(hwnd, x_ratio=0.145, y_ratio=0.07, clicks=1)
        points["search_box"] = {"x": x, "y": y}
        time.sleep(delay)
        pyautogui.press("backspace", presses=24, interval=0.01)
        pyperclip.copy(search)
        pyautogui.hotkey("ctrl", "v")
        time.sleep(delay)
        x, y = click_relative(hwnd, x_ratio=0.18, y_ratio=0.17, clicks=1)
        points["search_result"] = {"x": x, "y": y}
        time.sleep(delay)

    if message:
        x, y = click_relative(hwnd, x_ratio=0.72, y_ratio=0.93, clicks=1)
        points["input_box"] = {"x": x, "y": y}
        time.sleep(0.2)
        pyperclip.copy(message)
        pyautogui.hotkey("ctrl", "v")
        time.sleep(0.3)
        pyautogui.press("enter")
        time.sleep(delay)
    return points


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Debug helper for the live Weixin window")
    parser.add_argument("--process-path", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--search", default=None)
    parser.add_argument("--message", default=None)
    parser.add_argument("--delay", type=float, default=0.8)
    args = parser.parse_args(argv)

    chosen = locate_window(args.process_path)
    hwnd = int(chosen["hwnd"])
    bring_front(hwnd, chosen.get("title", ""))
    time.sleep(args.delay)
    focus_click = click_window(hwnd)
    time.sleep(0.4)
    before_send = foreground_info()
    interaction = maybe_search_and_send(hwnd, args.search, args.message, args.delay)
    current = locate_window(args.process_path)
    snap = capture_window(int(current["hwnd"]), Path(args.output))
    print(
        json.dumps(
            {
                "chosen_window": chosen,
                "focus_click": {"x": focus_click[0], "y": focus_click[1]},
                "foreground_before_capture": before_send,
                "interaction": interaction,
                "current_window": current,
                "capture": snap,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
