from __future__ import annotations

import os
import re
import json
import subprocess
import time
from pathlib import Path
from typing import Any

from .common import compact_text, stable_digest, utc_now

ENGINEERING_ACTION_SCHEMA = "holo.stage154.engineering_action.v1"

_SKIP_DIRS = {".git", ".holo_runtime", ".pytest_tmp", "__pycache__", "node_modules", ".venv", "venv"}
_DANGEROUS_COMMAND_PATTERNS = (
    r"\brm\s+-rf\b",
    r"\bgit\s+reset\s+--hard\b",
    r"\bgit\s+clean\b",
    r"\bdel\s+/s\b",
    r"\brmdir\s+/s\b",
    r"\bremove-item\b.*\b-recurse\b",
    r"\bcurl\b.*\|",
    r"\bwget\b.*\|",
    r"\bpip\s+install\b",
    r"\bpython\s+-m\s+pip\s+install\b",
    r"\bnpm\s+install\b",
    r"\byarn\s+add\b",
    r"\bpnpm\s+install\b",
    r"\bcat\b.*\.ssh",
    r"\btype\b.*\.ssh",
    r"\bget-content\b.*\.ssh",
    r"\bpowershell\b.*-enc",
)


def _compact(value: Any, limit: int = 280) -> str:
    return compact_text(" ".join(str(value or "").split()), limit)


def _repo_root(repo_root: str | os.PathLike[str]) -> Path:
    root = Path(repo_root).resolve()
    if not root.exists() or not root.is_dir():
        raise ValueError(f"repo root does not exist: {repo_root}")
    return root


def _safe_path(root: Path, path: str | os.PathLike[str]) -> Path:
    candidate = Path(path)
    if candidate.is_absolute():
        resolved = candidate.resolve()
    else:
        resolved = (root / candidate).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"path escapes workspace: {path}") from exc
    return resolved


def _rel(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root).as_posix()


def _action_row(
    *,
    action_type: str,
    input_payload: dict[str, Any] | None = None,
    status: str,
    stdout_summary: str = "",
    stderr_summary: str = "",
    files_read: list[str] | None = None,
    files_changed: list[str] | None = None,
    commands_run: list[str] | None = None,
    tests_run: list[str] | None = None,
    duration_ms: int = 0,
) -> dict[str, Any]:
    clean_input = dict(input_payload or {})
    observed_at = utc_now()
    action_id = "eng:" + stable_digest(
        action_type,
        json.dumps(clean_input, ensure_ascii=False, sort_keys=True),
        status,
        observed_at,
        limit=12,
    )
    return {
        "schema": ENGINEERING_ACTION_SCHEMA,
        "action_id": action_id,
        "action_type": action_type,
        "input": clean_input,
        "status": status,
        "stdout_summary": _compact(stdout_summary, 900),
        "stderr_summary": _compact(stderr_summary, 600),
        "files_read": list(files_read or []),
        "files_changed": list(files_changed or []),
        "commands_run": list(commands_run or []),
        "tests_run": list(tests_run or []),
        "duration_ms": int(max(0, duration_ms)),
        "observed_at": observed_at,
    }


def _is_text_candidate(path: Path, root: Path | None = None) -> bool:
    parts = path.parts
    if root is not None:
        try:
            parts = path.relative_to(root).parts
        except ValueError:
            parts = path.parts
    if any(part in _SKIP_DIRS for part in parts):
        return False
    try:
        return path.is_file() and path.stat().st_size <= 1_500_000
    except OSError:
        return False


def workspace_search(
    repo_root: str | os.PathLike[str],
    *,
    query: str,
    glob: str = "*",
    max_results: int = 40,
) -> dict[str, Any]:
    started = time.perf_counter()
    root = _repo_root(repo_root)
    current_query = str(query or "").strip()
    current_glob = str(glob or "*").strip() or "*"
    if not current_query:
        return _action_row(
            action_type="workspace_search",
            input_payload={"query": current_query, "glob": current_glob},
            status="empty",
            stderr_summary="empty search query",
            duration_ms=int((time.perf_counter() - started) * 1000),
        )

    lowered = current_query.lower()
    matches: list[str] = []
    files_read: list[str] = []
    for path in root.rglob(current_glob):
        if len(matches) >= max_results:
            break
        if not _is_text_candidate(path, root):
            continue
        rel_path = _rel(root, path)
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        file_had_match = False
        for line_no, line in enumerate(text.splitlines(), start=1):
            if lowered in line.lower():
                matches.append(f"{rel_path}:{line_no}: {line.strip()}")
                file_had_match = True
                if len(matches) >= max_results:
                    break
        if file_had_match:
            files_read.append(rel_path)
    status = "ok" if matches else "empty"
    return _action_row(
        action_type="workspace_search",
        input_payload={"query": current_query, "glob": current_glob, "max_results": max_results},
        status=status,
        stdout_summary="\n".join(matches) if matches else "no matches",
        files_read=sorted(dict.fromkeys(files_read)),
        duration_ms=int((time.perf_counter() - started) * 1000),
    )


def file_read(
    repo_root: str | os.PathLike[str],
    path: str | os.PathLike[str],
    *,
    start_line: int | None = None,
    end_line: int | None = None,
) -> dict[str, Any]:
    started = time.perf_counter()
    root = _repo_root(repo_root)
    input_payload = {"path": str(path), "start_line": start_line, "end_line": end_line}
    try:
        target = _safe_path(root, path)
    except ValueError as exc:
        return _action_row(
            action_type="file_read",
            input_payload=input_payload,
            status="rejected",
            stderr_summary=str(exc),
            duration_ms=int((time.perf_counter() - started) * 1000),
        )
    if not target.exists() or not target.is_file():
        return _action_row(
            action_type="file_read",
            input_payload=input_payload,
            status="error",
            stderr_summary=f"file not found: {path}",
            duration_ms=int((time.perf_counter() - started) * 1000),
        )
    try:
        lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as exc:
        return _action_row(
            action_type="file_read",
            input_payload=input_payload,
            status="error",
            stderr_summary=str(exc),
            duration_ms=int((time.perf_counter() - started) * 1000),
        )
    first = max(1, int(start_line or 1))
    last = min(len(lines), int(end_line or len(lines)))
    selected = [f"{line_no}: {lines[line_no - 1]}" for line_no in range(first, last + 1) if 1 <= line_no <= len(lines)]
    return _action_row(
        action_type="file_read",
        input_payload=input_payload,
        status="ok",
        stdout_summary="\n".join(selected),
        files_read=[_rel(root, target)],
        duration_ms=int((time.perf_counter() - started) * 1000),
    )


def _patch_paths(patch_text: str) -> list[str]:
    paths: list[str] = []
    for raw_line in str(patch_text or "").splitlines():
        line = raw_line.strip()
        for prefix in ("+++ b/", "--- a/"):
            if line.startswith(prefix):
                value = line[len(prefix) :].strip()
                if value and value != "/dev/null":
                    paths.append(value)
        if line.startswith("diff --git "):
            parts = line.split()
            for part in parts[2:4]:
                if part.startswith("a/") or part.startswith("b/"):
                    paths.append(part[2:])
    return sorted(dict.fromkeys(paths))


def apply_patch(repo_root: str | os.PathLike[str], patch_text: str) -> dict[str, Any]:
    started = time.perf_counter()
    root = _repo_root(repo_root)
    patch = str(patch_text or "")
    changed_paths = _patch_paths(patch)
    input_payload = {"patch_digest": "patch:" + stable_digest(patch, limit=12), "changed_paths": changed_paths}
    if not patch.strip():
        return _action_row(
            action_type="apply_patch",
            input_payload=input_payload,
            status="empty",
            stderr_summary="empty patch",
            duration_ms=int((time.perf_counter() - started) * 1000),
        )
    try:
        for rel_path in changed_paths:
            _safe_path(root, rel_path)
    except ValueError as exc:
        return _action_row(
            action_type="apply_patch",
            input_payload=input_payload,
            status="rejected",
            stderr_summary=str(exc),
            duration_ms=int((time.perf_counter() - started) * 1000),
        )
    check = subprocess.run(
        ["git", "apply", "--check", "-"],
        cwd=root,
        input=patch,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=20,
        check=False,
    )
    if check.returncode != 0:
        return _action_row(
            action_type="apply_patch",
            input_payload=input_payload,
            status="error",
            stdout_summary=check.stdout,
            stderr_summary=check.stderr,
            duration_ms=int((time.perf_counter() - started) * 1000),
        )
    applied = subprocess.run(
        ["git", "apply", "-"],
        cwd=root,
        input=patch,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=20,
        check=False,
    )
    return _action_row(
        action_type="apply_patch",
        input_payload=input_payload,
        status="ok" if applied.returncode == 0 else "error",
        stdout_summary=applied.stdout or ("applied patch" if applied.returncode == 0 else ""),
        stderr_summary=applied.stderr,
        files_changed=changed_paths if applied.returncode == 0 else [],
        duration_ms=int((time.perf_counter() - started) * 1000),
    )


def _dangerous_command_reason(command: str) -> str:
    lowered = str(command or "").lower()
    for pattern in _DANGEROUS_COMMAND_PATTERNS:
        if re.search(pattern, lowered):
            return f"dangerous command rejected by Stage154 policy: {pattern}"
    return ""


def test_run(repo_root: str | os.PathLike[str], command: str, *, timeout_seconds: int = 60) -> dict[str, Any]:
    started = time.perf_counter()
    root = _repo_root(repo_root)
    current = str(command or "").strip()
    reason = _dangerous_command_reason(current)
    if reason:
        return _action_row(
            action_type="test_run",
            input_payload={"command": current},
            status="rejected",
            stderr_summary=reason,
            duration_ms=int((time.perf_counter() - started) * 1000),
        )
    if not current:
        return _action_row(
            action_type="test_run",
            input_payload={"command": current},
            status="empty",
            stderr_summary="empty command",
            duration_ms=int((time.perf_counter() - started) * 1000),
        )
    try:
        result = subprocess.run(
            current,
            cwd=root,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return _action_row(
            action_type="test_run",
            input_payload={"command": current},
            status="error",
            stderr_summary=str(exc),
            commands_run=[current],
            tests_run=[current],
            duration_ms=int((time.perf_counter() - started) * 1000),
        )
    return _action_row(
        action_type="test_run",
        input_payload={"command": current, "timeout_seconds": timeout_seconds},
        status="ok" if result.returncode == 0 else "error",
        stdout_summary=result.stdout,
        stderr_summary=result.stderr,
        commands_run=[current],
        tests_run=[current],
        duration_ms=int((time.perf_counter() - started) * 1000),
    )


def _git_command(repo_root: str | os.PathLike[str], args: list[str], *, action_type: str, path: str | None = None) -> dict[str, Any]:
    started = time.perf_counter()
    root = _repo_root(repo_root)
    command = "git " + " ".join(args)
    input_payload: dict[str, Any] = {"command": command}
    if path:
        try:
            target = _safe_path(root, path)
        except ValueError as exc:
            return _action_row(
                action_type=action_type,
                input_payload={"path": path},
                status="rejected",
                stderr_summary=str(exc),
                duration_ms=int((time.perf_counter() - started) * 1000),
            )
        input_payload["path"] = _rel(root, target)
    result = subprocess.run(
        ["git", *args],
        cwd=root,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=30,
        check=False,
    )
    return _action_row(
        action_type=action_type,
        input_payload=input_payload,
        status="ok" if result.returncode == 0 else "error",
        stdout_summary=result.stdout or ("clean" if result.returncode == 0 else ""),
        stderr_summary=result.stderr,
        commands_run=[command],
        duration_ms=int((time.perf_counter() - started) * 1000),
    )


def git_status(repo_root: str | os.PathLike[str]) -> dict[str, Any]:
    return _git_command(repo_root, ["status", "--short"], action_type="git_status")


def git_diff(repo_root: str | os.PathLike[str], path: str | None = None) -> dict[str, Any]:
    args = ["diff", "--"]
    if path:
        args.append(str(path))
    return _git_command(repo_root, args, action_type="git_diff", path=path)


test_run.__test__ = False
