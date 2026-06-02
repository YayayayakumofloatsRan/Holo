from __future__ import annotations


THEME = {
    "blue": "34",
    "bold_cyan": "1;36",
    "bold_green": "1;32",
    "bold_magenta": "1;35",
    "bold_red": "1;31",
    "bold_yellow": "1;33",
    "cyan": "36",
    "dim": "2",
    "green": "32",
    "magenta": "35",
    "red": "31",
    "white": "37",
    "yellow": "33",
}


EVENT_STYLES = {
    "action": "bold_yellow",
    "answer": "bold_green",
    "chat": "bold_green",
    "context": "dim",
    "evidence": "green",
    "failure": "bold_red",
    "final": "bold_green",
    "memory": "magenta",
    "model": "bold_cyan",
    "observe": "green",
    "policy": "yellow",
    "reason": "bold_magenta",
    "retrieval": "blue",
    "route": "magenta",
    "tool": "bold_yellow",
}


def status_style(status: str) -> str:
    if status in {"completed", "ok", "ready"}:
        return "green"
    if status in {"needs_user_input", "blocked", "canceled"}:
        return "yellow"
    if status in {"failed", "error"}:
        return "red"
    return "cyan"


def event_style(category: str, *, status: str | None = None) -> str:
    if status in {"failed", "error", "blocked"}:
        return "bold_red" if status in {"failed", "error"} else "bold_yellow"
    if status in {"completed", "ok", "ready", "sufficient"}:
        return "green"
    return EVENT_STYLES.get(category, "dim")


def style(text: str, style_name: str, *, color: bool) -> str:
    if not color:
        return text
    code = THEME.get(style_name)
    return f"\033[{code}m{text}\033[0m" if code else text
