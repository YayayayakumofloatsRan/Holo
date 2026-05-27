from __future__ import annotations

from typing import Any

PUBLIC_METADATA_SANITIZER_SCHEMA = "holo.stage159.public_metadata_sanitizer.v1"

PRIVATE_KEYS = {
    "reasoning_content",
    "chain_of_thought",
    "hidden_reasoning",
    "messages",
    "assistant_messages_internal",
    "internal_messages",
    "final_decoded",
    "raw_decoded",
}

STAGE152_PUBLIC_KEYS = {
    "schema",
    "status",
    "tool_call_count",
    "executed_count",
    "round_count",
    "final_request_sent",
    "stop_reason",
    "exhausted",
    "usage",
    "reasoning_content_retained_count",
    "tool_observation_ledger",
    "web_observation_ledger",
    "memory_observation_ledger",
    "time_observation",
    "grounding",
    "live_trace",
}


def _private_key(key: Any) -> bool:
    return str(key or "").strip().lower() in PRIVATE_KEYS


def sanitize_public_metadata(value: Any) -> Any:
    """Recursively remove provider-private reasoning and internal packets."""

    if isinstance(value, dict):
        clean: dict[Any, Any] = {}
        for key, item in value.items():
            if _private_key(key):
                continue
            cleaned = sanitize_public_metadata(item)
            if cleaned == {} or cleaned == []:
                continue
            clean[key] = cleaned
        return clean
    if isinstance(value, list):
        cleaned_items = [sanitize_public_metadata(item) for item in value]
        return [item for item in cleaned_items if item != {} and item != []]
    if isinstance(value, tuple):
        return tuple(sanitize_public_metadata(item) for item in value)
    return value


def build_public_stage152_report(stage152_report: dict[str, Any]) -> dict[str, Any]:
    """Return the public Stage152 report shape used by reply/archive/CLI surfaces."""

    source = dict(stage152_report or {})
    public = {key: source.get(key) for key in STAGE152_PUBLIC_KEYS if key in source}
    return sanitize_public_metadata(public)


def assert_no_private_reasoning(value: Any) -> tuple[bool, list[str]]:
    paths: list[str] = []

    def visit(item: Any, path: str) -> None:
        if isinstance(item, dict):
            for key, child in item.items():
                child_path = f"{path}.{key}" if path else str(key)
                if _private_key(key):
                    paths.append(child_path)
                    continue
                visit(child, child_path)
        elif isinstance(item, list):
            for index, child in enumerate(item):
                visit(child, f"{path}[{index}]")
        elif isinstance(item, tuple):
            for index, child in enumerate(item):
                visit(child, f"{path}[{index}]")

    visit(value, "")
    return not paths, paths
