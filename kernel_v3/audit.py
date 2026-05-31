from __future__ import annotations

import hashlib
from collections.abc import Mapping

from kernel_v3.contracts import JsonObject, JsonValue


DEFAULT_SAFE_ACCESS_CONTEXT_KEYS = {
    "command",
    "context_id",
    "corpus_document_id",
    "document_id",
    "goal_id",
    "memory_id",
    "mode",
    "plan_id",
    "profile_id",
    "provider_id",
    "rank_query_hash",
    "run_id",
    "source_id",
    "step_id",
    "surface",
    "task_id",
    "thread_id",
    "usage",
}

_SENSITIVE_KEY_FRAGMENTS = (
    "authorization",
    "body",
    "content",
    "cookie",
    "credential",
    "env",
    "password",
    "payload",
    "private_key",
    "raw",
    "secret",
    "token",
)


def safe_access_context(
    context: Mapping[str, object],
    *,
    safe_string_keys: set[str] | None = None,
    string_limit: int = 160,
) -> JsonObject:
    safe_keys = set(DEFAULT_SAFE_ACCESS_CONTEXT_KEYS)
    if safe_string_keys is not None:
        safe_keys.update(safe_string_keys)
    safe: JsonObject = {}
    for raw_key, raw_value in context.items():
        key = str(raw_key)
        normalized = key.lower()
        if _is_sensitive_key(normalized):
            safe[key] = "[omitted]"
            continue
        safe[key] = _safe_context_value(
            raw_value,
            allow_string=normalized in safe_keys,
            safe_string_keys=safe_keys,
            string_limit=string_limit,
        )
    return safe


def _safe_context_value(
    value: object,
    *,
    allow_string: bool,
    safe_string_keys: set[str],
    string_limit: int,
) -> JsonValue:
    if value is None or isinstance(value, bool | int | float):
        return value
    if isinstance(value, str):
        if allow_string:
            return value if len(value) <= string_limit else value[: max(0, string_limit - 3)] + "..."
        return {
            "sha256": hashlib.sha256(value.encode("utf-8")).hexdigest(),
            "length": len(value),
            "redacted": True,
        }
    if isinstance(value, list):
        return [
            _safe_context_value(
                item,
                allow_string=allow_string,
                safe_string_keys=safe_string_keys,
                string_limit=string_limit,
            )
            for item in value[:16]
        ]
    if isinstance(value, dict):
        return safe_access_context(
            {str(key): item for key, item in value.items()},
            safe_string_keys=safe_string_keys,
            string_limit=string_limit,
        )
    return {
        "type": value.__class__.__name__,
        "redacted": True,
    }


def _is_sensitive_key(normalized_key: str) -> bool:
    if normalized_key == "key" or normalized_key.endswith("_key") or normalized_key.endswith("-key"):
        return True
    if normalized_key == "text" or normalized_key.endswith("_text") or normalized_key.endswith("-text"):
        return True
    return any(fragment in normalized_key for fragment in _SENSITIVE_KEY_FRAGMENTS)
