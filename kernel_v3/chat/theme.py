from __future__ import annotations


THEME = {
    "bold_gray": "1;90",
    "bold_green": "1;32",
    "bold_orange": "1;38;5;208",
    "bold_red": "1;31",
    "bold_white": "1;37",
    "gray": "90",
    "gray_green": "38;5;108",
    "gray_orange": "38;5;172",
    "gray_red": "38;5;167",
    "dim": "2",
    "green": "32",
    "light": "97",
    "orange": "38;5;208",
    "red": "31",
    "white": "37",
}


EVENT_STYLES = {
    "action": "gray_orange",
    "answer": "bold_green",
    "chat": "gray_green",
    "context": "dim",
    "evidence": "gray_green",
    "failure": "bold_red",
    "final": "bold_green",
    "memory": "gray",
    "model": "bold_white",
    "observe": "gray_green",
    "policy": "gray_orange",
    "reason": "gray",
    "retrieval": "white",
    "route": "gray",
    "tool": "gray_orange",
}


def status_style(status: str) -> str:
    if status in {"completed", "ok", "ready"}:
        return "green"
    if status in {"needs_user_input", "blocked", "canceled"}:
        return "orange"
    if status in {"failed", "error"}:
        return "red"
    return "white"


def event_style(category: str, *, status: str | None = None) -> str:
    if status in {"failed", "error", "blocked"}:
        return "bold_red" if status in {"failed", "error"} else "bold_orange"
    if status in {"completed", "ok", "ready", "sufficient"}:
        return "green"
    return EVENT_STYLES.get(category, "dim")


def style(text: str, style_name: str, *, color: bool) -> str:
    if not color:
        return text
    code = THEME.get(style_name)
    return f"\033[{code}m{text}\033[0m" if code else text
