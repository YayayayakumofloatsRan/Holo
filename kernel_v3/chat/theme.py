from __future__ import annotations


THEME = {
    "bold_cyan": "1;36",
    "bold_green": "1;32",
    "cyan": "36",
    "dim": "2",
    "green": "32",
    "red": "31",
    "yellow": "33",
}


def status_style(status: str) -> str:
    if status in {"completed", "ok", "ready"}:
        return "green"
    if status in {"needs_user_input", "blocked", "canceled"}:
        return "yellow"
    if status in {"failed", "error"}:
        return "red"
    return "cyan"


def style(text: str, style_name: str, *, color: bool) -> str:
    if not color:
        return text
    code = THEME.get(style_name)
    return f"\033[{code}m{text}\033[0m" if code else text
