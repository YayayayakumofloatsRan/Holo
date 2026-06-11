from __future__ import annotations

import ast
import json
import re
from dataclasses import dataclass

from kernel_v3.contracts import JsonObject


@dataclass(frozen=True, kw_only=True)
class JsonParseResult:
    value: JsonObject | None
    repaired: bool
    attempts: int
    error: str | None = None


def parse_json_object(text: str, *, max_repair_attempts: int = 1) -> JsonParseResult:
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        last_error = f"{type(exc).__name__}: {exc.msg}"
    else:
        if isinstance(value, dict):
            return JsonParseResult(value=value, repaired=False, attempts=0)
        return JsonParseResult(value=None, repaired=False, attempts=0, error="json_root_not_object")

    candidate = text
    for attempt in range(1, max(0, max_repair_attempts) + 1):
        candidate = _repair_once(candidate)
        try:
            value = json.loads(candidate)
        except json.JSONDecodeError as exc:
            last_error = f"{type(exc).__name__}: {exc.msg}"
            continue
        if isinstance(value, dict):
            return JsonParseResult(value=value, repaired=True, attempts=attempt)
        last_error = "json_root_not_object"
    literal = _parse_python_literal_object(candidate)
    if literal is not None:
        return JsonParseResult(value=literal, repaired=True, attempts=max(1, max(0, max_repair_attempts)))
    return JsonParseResult(value=None, repaired=False, attempts=max(0, max_repair_attempts), error=last_error)


def _repair_once(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        stripped = "\n".join(lines).strip()
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start >= 0 and end > start:
        stripped = stripped[start : end + 1]
    stripped = re.sub(r",(\s*[}\]])", r"\1", stripped)
    return stripped


def _parse_python_literal_object(text: str) -> JsonObject | None:
    stripped = text.strip()
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start >= 0 and end > start:
        stripped = stripped[start : end + 1]
    try:
        value = ast.literal_eval(stripped)
    except (SyntaxError, ValueError):
        return None
    if not isinstance(value, dict):
        return None
    try:
        return json.loads(json.dumps(value, ensure_ascii=False))
    except (TypeError, ValueError):
        return None
