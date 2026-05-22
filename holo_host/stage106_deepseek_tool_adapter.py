from __future__ import annotations

import copy
import json
from typing import Any

STAGE106_SCHEMA = "holo.stage106.deepseek_tool_adapter.v1"


TOOL_REGISTRY: dict[str, dict[str, Any]] = {
    "external_lookup": {
        "description": (
            "Request current external evidence before answering. Holo validates and executes this; "
            "the provider only proposes the call."
        ),
        "parameters": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The exact current-fact lookup query to resolve.",
                    "minLength": 1,
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum evidence snippets requested.",
                    "minimum": 1,
                    "maximum": 8,
                },
                "source_hint": {
                    "type": "string",
                    "description": "Optional source class or provider hint.",
                },
            },
            "required": ["query"],
        },
    },
    "memory_recall": {
        "description": (
            "Request local Holo memory recall. This is read-only and must stay inside the WSL brain."
        ),
        "parameters": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The semantic recall query.",
                    "minLength": 1,
                },
                "thread_key": {
                    "type": "string",
                    "description": "Optional Holo thread key.",
                },
                "chat_name": {
                    "type": "string",
                    "description": "Optional visible chat name.",
                },
                "channel": {
                    "type": "string",
                    "description": "Optional transport channel.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum memory anchors requested.",
                    "minimum": 1,
                    "maximum": 12,
                },
            },
            "required": ["query"],
        },
    },
    "workspace_inspect": {
        "description": (
            "Inspect the local Holo workspace through bounded read-only operations: list directories, "
            "read files, or search text. Holo executes this locally inside the WSL brain."
        ),
        "parameters": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "operation": {
                    "type": "string",
                    "description": "One of list_dir, read_file, or search_text.",
                },
                "path": {
                    "type": "string",
                    "description": "Workspace-relative path to inspect.",
                },
                "query": {
                    "type": "string",
                    "description": "Plain text query for search_text.",
                },
                "glob": {
                    "type": "string",
                    "description": "Optional file glob for search_text.",
                },
                "start_line": {
                    "type": "integer",
                    "description": "Optional 1-based first line for read_file.",
                    "minimum": 1,
                },
                "end_line": {
                    "type": "integer",
                    "description": "Optional 1-based last line for read_file.",
                    "minimum": 1,
                },
                "max_chars": {
                    "type": "integer",
                    "description": "Maximum text characters returned.",
                    "minimum": 1,
                    "maximum": 12000,
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum entries or search hits.",
                    "minimum": 1,
                    "maximum": 80,
                },
            },
            "required": ["operation"],
        },
    },
    "local_command": {
        "description": (
            "Run a strictly allowlisted local workspace command for verification. Commands are passed as argv, "
            "never through a shell, and Holo rejects destructive or unknown commands."
        ),
        "parameters": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "argv": {
                    "type": "array",
                    "description": "Command argv. Allowed examples include git status --short and python -m pytest ...",
                    "items": {"type": "string"},
                    "minItems": 1,
                    "maxItems": 32,
                },
                "cwd": {
                    "type": "string",
                    "description": "Optional workspace-relative working directory.",
                },
                "timeout_seconds": {
                    "type": "integer",
                    "description": "Command timeout in seconds.",
                    "minimum": 1,
                    "maximum": 60,
                },
            },
            "required": ["argv"],
        },
    },
    "workspace_edit": {
        "description": (
            "Apply bounded text edits inside the Holo workspace. Supports write_file, append_text, "
            "and replace_text. Holo rejects paths outside the workspace and protected runtime paths."
        ),
        "parameters": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "operation": {
                    "type": "string",
                    "description": "One of write_file, append_text, or replace_text.",
                },
                "path": {
                    "type": "string",
                    "description": "Workspace-relative text file path.",
                },
                "content": {
                    "type": "string",
                    "description": "Text content for write_file or append_text.",
                },
                "old_text": {
                    "type": "string",
                    "description": "Exact text to replace for replace_text.",
                },
                "new_text": {
                    "type": "string",
                    "description": "Replacement text for replace_text.",
                },
                "create_dirs": {
                    "type": "boolean",
                    "description": "Whether parent directories may be created.",
                },
            },
            "required": ["operation", "path"],
        },
    },
    "git_inspect": {
        "description": "Inspect local git state through bounded read-only git commands.",
        "parameters": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "operation": {
                    "type": "string",
                    "description": "One of status_short, diff_check, diff_stat, or log_latest.",
                },
                "path": {
                    "type": "string",
                    "description": "Optional workspace-relative path for status or diff operations.",
                },
            },
            "required": ["operation"],
        },
    },
    "test_runner": {
        "description": "Run bounded local pytest checks through argv, without shell execution.",
        "parameters": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "path_patterns": {
                    "type": "array",
                    "description": "Workspace-relative pytest path arguments.",
                    "items": {"type": "string"},
                    "maxItems": 12,
                },
                "keyword": {
                    "type": "string",
                    "description": "Optional pytest -k expression.",
                },
                "timeout_seconds": {
                    "type": "integer",
                    "description": "Command timeout in seconds.",
                    "minimum": 1,
                    "maximum": 120,
                },
            },
        },
    },
    "progress_note": {
        "description": "Append a short local progress note under docs/agent_progress_notes.",
        "parameters": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "title": {
                    "type": "string",
                    "description": "Short title for the note.",
                },
                "summary": {
                    "type": "string",
                    "description": "Progress summary to append.",
                },
                "category": {
                    "type": "string",
                    "description": "Optional category slug.",
                },
            },
            "required": ["title", "summary"],
        },
    },
}


def _request_to_dict(request: Any) -> dict[str, Any]:
    if isinstance(request, dict):
        return dict(request)
    to_dict = getattr(request, "to_dict", None)
    if callable(to_dict):
        payload = to_dict()
        return dict(payload) if isinstance(payload, dict) else {}
    name = str(getattr(request, "name", "") or "").strip()
    if not name:
        return {}
    return {
        "name": name,
        "reason": str(getattr(request, "reason", "") or ""),
        "payload": dict(getattr(request, "payload", {}) or {}),
    }


def _tool_names(tool_requests: Any) -> list[str]:
    names: list[str] = []
    for request in list(tool_requests or []):
        item = _request_to_dict(request)
        name = str(item.get("name", "") or "").strip()
        if name and name not in names:
            names.append(name)
    return names


def _tool_schema(name: str) -> dict[str, Any]:
    definition = TOOL_REGISTRY[name]
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": str(definition["description"]),
            "parameters": copy.deepcopy(definition["parameters"]),
        },
    }


def build_tool_payload(tool_requests: Any, *, tool_choice: Any = "auto") -> dict[str, Any]:
    tools = [_tool_schema(name) for name in _tool_names(tool_requests) if name in TOOL_REGISTRY]
    if not tools:
        return {"tools": [], "tool_choice": "none"}
    if isinstance(tool_choice, dict):
        choice: Any = dict(tool_choice)
    else:
        choice = str(tool_choice or "auto").strip() or "auto"
    return {"tools": tools, "tool_choice": choice}


def build_stage106_deepseek_adapter_plan(
    tool_requests: Any,
    *,
    query: str = "",
    tool_choice: str = "auto",
) -> dict[str, Any]:
    requested_names = _tool_names(tool_requests)
    provider_payload = build_tool_payload(tool_requests, tool_choice=tool_choice)
    exposed_names = [tool["function"]["name"] for tool in provider_payload.get("tools", [])]
    rejected_names = [name for name in requested_names if name not in TOOL_REGISTRY]
    return {
        "schema": STAGE106_SCHEMA,
        "stage": 106,
        "query": str(query or ""),
        "tool_count": len(exposed_names),
        "requested_tools": requested_names,
        "exposed_tools": exposed_names,
        "rejected_tools": rejected_names,
        "provider_payload": provider_payload,
        "authority": {
            "provider_may_propose_tools": bool(exposed_names),
            "provider_may_execute_tools": False,
            "executor": "holo_wsl_brain",
            "unknown_tools_rejected": True,
            "arguments_must_be_json_object": True,
        },
        "loop_contract": [
            "stage105 emits bounded tool affordance",
            "stage106 exposes allowlisted provider tool schema",
            "provider returns tool_calls",
            "holo validates and executes locally",
            "tool observation is compressed into the next provider packet",
        ],
    }


def _first_message(decoded: Any) -> dict[str, Any]:
    if not isinstance(decoded, dict):
        return {}
    choices = list(decoded.get("choices", []) or [])
    if not choices or not isinstance(choices[0], dict):
        return {}
    message = choices[0].get("message", {})
    return dict(message) if isinstance(message, dict) else {}


def _parse_arguments(raw: Any) -> tuple[dict[str, Any], str]:
    if isinstance(raw, dict):
        return dict(raw), ""
    if not isinstance(raw, str):
        return {}, "arguments_not_object"
    try:
        decoded = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return {}, "arguments_not_json"
    if not isinstance(decoded, dict):
        return {}, "arguments_not_object"
    return decoded, ""


def _validate_arguments(name: str, arguments: dict[str, Any]) -> str:
    schema = dict(TOOL_REGISTRY.get(name, {}).get("parameters", {}))
    required = list(schema.get("required", []) or [])
    for key in required:
        if key not in arguments or str(arguments.get(key, "") or "").strip() == "":
            return f"missing_required:{key}"
    return ""


def parse_provider_tool_calls(decoded: Any) -> list[dict[str, Any]]:
    message = _first_message(decoded)
    calls = list(message.get("tool_calls", []) or [])
    parsed: list[dict[str, Any]] = []
    for index, call in enumerate(calls):
        item = dict(call) if isinstance(call, dict) else {}
        function = item.get("function", {})
        function_payload = dict(function) if isinstance(function, dict) else {}
        name = str(function_payload.get("name", "") or "").strip()
        call_id = str(item.get("id", "") or f"tool_call_{index + 1}")
        arguments, argument_error = _parse_arguments(function_payload.get("arguments", {}))
        error = ""
        if name not in TOOL_REGISTRY:
            error = "unknown_tool"
        elif argument_error:
            error = argument_error
        else:
            error = _validate_arguments(name, arguments)
        parsed.append(
            {
                "id": call_id,
                "type": str(item.get("type", "function") or "function"),
                "name": name,
                "arguments": arguments,
                "allowed": not bool(error),
                "status": "rejected" if error else "accepted",
                "error": error,
            }
        )
    return parsed
