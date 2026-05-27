from __future__ import annotations

import os
import shlex
from pathlib import Path

SAFE_COMMAND_POLICY_SCHEMA = "holo.stage159.safe_command_policy.v1"

_CHAIN_TOKENS = {"&&", "||", ";", "|", ">", ">>", "<", "$(", "`"}
_BLOCKED_WORDS = {
    "curl",
    "wget",
    "pip",
    "install",
    "rm",
    "rmdir",
    "del",
    "erase",
    "clean",
    "reset",
    "credential",
    ".env",
    "id_rsa",
}


def _split(command: str) -> list[str]:
    return shlex.split(str(command or ""), posix=os.name != "nt")


def _looks_like_path(token: str) -> bool:
    if not token or token.startswith("-"):
        return False
    if "::" in token:
        token = token.split("::", 1)[0]
    return (
        "/" in token
        or "\\" in token
        or token.startswith(".")
        or token.endswith((".py", ".md", ".txt", ".json", ".toml", ".yaml", ".yml"))
    )


def _path_inside_repo(token: str, repo_root: str | os.PathLike[str] | None) -> bool:
    if repo_root is None or not _looks_like_path(token):
        return True
    current = token.split("::", 1)[0]
    root = Path(repo_root).resolve()
    candidate = (root / current).resolve() if not Path(current).is_absolute() else Path(current).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return False
    return True


def _blocked(argv: list[str]) -> bool:
    lowered = [item.lower() for item in argv]
    if any(token in argv for token in _CHAIN_TOKENS):
        return True
    joined = " ".join(lowered)
    if any(mark in joined for mark in ("&&", "||", ">", "<", "$(", "`")):
        return True
    if any(word in _BLOCKED_WORDS for word in lowered):
        if lowered[:2] == ["git", "diff"]:
            return False
        if lowered[:2] == ["git", "status"]:
            return False
        return True
    return False


def parse_allowed_command(command: str, *, repo_root: str | os.PathLike[str] | None = None) -> tuple[list[str], str]:
    """Parse a Stage159 allowlisted engineering command.

    Returns `(argv, "")` when accepted, or `([], reason)` when rejected.
    """

    current = str(command or "").strip()
    if not current:
        return [], "empty_command"
    try:
        argv = _split(current)
    except ValueError:
        return [], "command_not_allowlisted"
    if not argv or _blocked(argv):
        return [], "command_not_allowlisted"

    lowered = [item.lower() for item in argv]
    allowed = False
    path_tokens: list[str] = []
    if len(lowered) >= 3 and lowered[0] in {"python", "python3"} and lowered[1:3] == ["-m", "pytest"]:
        allowed = True
        path_tokens = argv[3:]
    elif lowered and lowered[0] == "pytest":
        allowed = True
        path_tokens = argv[1:]
    elif lowered == ["python", "scripts/check_public_release_hygiene.py"] or lowered == [
        "python3",
        "scripts/check_public_release_hygiene.py",
    ]:
        allowed = True
        path_tokens = argv[1:]
    elif lowered == ["git", "status", "--short"]:
        allowed = True
    elif len(lowered) >= 3 and lowered[:3] == ["git", "diff", "--"]:
        allowed = len(lowered) in {3, 4}
        path_tokens = argv[3:]

    if not allowed:
        return [], "command_not_allowlisted"
    for token in path_tokens:
        if token.startswith("-"):
            continue
        if not _path_inside_repo(token, repo_root):
            return [], "path_escape"
    return argv, ""
