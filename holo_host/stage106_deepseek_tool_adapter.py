from __future__ import annotations

import copy
import html
import json
import re
from typing import Any

STAGE106_SCHEMA = "holo.stage106.deepseek_tool_adapter.v1"

_DSML_TOOL_BLOCK_RE = re.compile(r"<[^<>]*tool_calls[^<>]*>(?P<body>.*?)</[^<>]*tool_calls>", re.DOTALL)
_DSML_INVOKE_RE = re.compile(r"<[^<>]*invoke\s+name=\"(?P<name>[^\"]+)\"[^<>]*>(?P<body>.*?)</[^<>]*invoke>", re.DOTALL)
_DSML_PARAMETER_RE = re.compile(
    r"<[^<>]*parameter\s+name=\"(?P<name>[^\"]+)\"\s+string=\"(?P<string>[^\"]+)\"[^<>]*>"
    r"(?P<value>.*?)</[^<>]*parameter>",
    re.DOTALL,
)


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


def _object_parameters(properties: dict[str, Any], required: list[str] | tuple[str, ...] = ()) -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": properties,
        "required": list(required),
    }


_PATH_PROPERTY = {"type": "string", "description": "Workspace-relative path."}
_QUERY_PROPERTY = {"type": "string", "description": "Plain text query.", "minLength": 1}
_MAX_RESULTS_PROPERTY = {
    "type": "integer",
    "description": "Maximum returned rows.",
    "minimum": 1,
    "maximum": 120,
}
_MAX_CHARS_PROPERTY = {
    "type": "integer",
    "description": "Maximum text characters returned.",
    "minimum": 1,
    "maximum": 20000,
}
_ARGV_PROPERTY = {
    "type": "array",
    "description": "Command argv. Shell strings are not accepted.",
    "items": {"type": "string"},
    "minItems": 1,
    "maxItems": 40,
}


TOOL_REGISTRY.update(
    {
        "file_read": {
            "description": "Read a bounded UTF-8 text file from the workspace.",
            "parameters": _object_parameters(
                {
                    "path": _PATH_PROPERTY,
                    "start_line": {"type": "integer", "minimum": 1},
                    "end_line": {"type": "integer", "minimum": 1},
                    "max_chars": _MAX_CHARS_PROPERTY,
                },
                ["path"],
            ),
        },
        "file_list": {
            "description": "List files and directories under a workspace path.",
            "parameters": _object_parameters(
                {"path": _PATH_PROPERTY, "max_results": _MAX_RESULTS_PROPERTY},
            ),
        },
        "file_search": {
            "description": "Search workspace text files for a plain text query.",
            "parameters": _object_parameters(
                {
                    "path": _PATH_PROPERTY,
                    "query": _QUERY_PROPERTY,
                    "glob": {"type": "string", "description": "Optional file glob."},
                    "max_results": _MAX_RESULTS_PROPERTY,
                },
                ["query"],
            ),
        },
        "file_stat": {
            "description": "Return basic metadata for one workspace file or directory.",
            "parameters": _object_parameters({"path": _PATH_PROPERTY}, ["path"]),
        },
        "directory_tree": {
            "description": "Return a bounded recursive directory tree.",
            "parameters": _object_parameters(
                {
                    "path": _PATH_PROPERTY,
                    "max_depth": {"type": "integer", "minimum": 1, "maximum": 5},
                    "max_entries": _MAX_RESULTS_PROPERTY,
                },
            ),
        },
        "json_read": {
            "description": "Read and parse a workspace JSON file, returning keys and bounded content.",
            "parameters": _object_parameters({"path": _PATH_PROPERTY, "max_chars": _MAX_CHARS_PROPERTY}, ["path"]),
        },
        "toml_read": {
            "description": "Read and parse a workspace TOML file, returning keys and bounded content.",
            "parameters": _object_parameters({"path": _PATH_PROPERTY, "max_chars": _MAX_CHARS_PROPERTY}, ["path"]),
        },
        "markdown_outline": {
            "description": "Extract heading outline from a workspace Markdown file.",
            "parameters": _object_parameters({"path": _PATH_PROPERTY, "max_results": _MAX_RESULTS_PROPERTY}, ["path"]),
        },
        "symbol_search": {
            "description": "Search source files for a symbol-like text query.",
            "parameters": _object_parameters(
                {
                    "path": _PATH_PROPERTY,
                    "query": _QUERY_PROPERTY,
                    "glob": {"type": "string", "description": "Optional source glob."},
                    "max_results": _MAX_RESULTS_PROPERTY,
                },
                ["query"],
            ),
        },
        "repo_overview": {
            "description": "Summarize workspace top-level structure and git status.",
            "parameters": _object_parameters({"max_results": _MAX_RESULTS_PROPERTY}),
        },
        "git_status": {
            "description": "Read local git status in short form.",
            "parameters": _object_parameters({"path": _PATH_PROPERTY}),
        },
        "git_diff": {
            "description": "Read bounded git diff diagnostics.",
            "parameters": _object_parameters(
                {
                    "operation": {"type": "string", "description": "One of stat or check."},
                    "path": _PATH_PROPERTY,
                },
            ),
        },
        "git_log": {
            "description": "Read the latest local git commit summary.",
            "parameters": _object_parameters({"limit": {"type": "integer", "minimum": 1, "maximum": 10}}),
        },
        "test_discover": {
            "description": "Discover likely local pytest test files without running them.",
            "parameters": _object_parameters(
                {
                    "path": _PATH_PROPERTY,
                    "glob": {"type": "string", "description": "Optional test file glob."},
                    "max_results": _MAX_RESULTS_PROPERTY,
                },
            ),
        },
        "python_module_check": {
            "description": "Parse a Python source file with ast to catch syntax errors without writing pyc files.",
            "parameters": _object_parameters({"path": _PATH_PROPERTY}, ["path"]),
        },
        "config_inspect": {
            "description": "Read the bounded Holo host config file or another workspace config path.",
            "parameters": _object_parameters({"path": _PATH_PROPERTY, "max_chars": _MAX_CHARS_PROPERTY}),
        },
        "runtime_health": {
            "description": "Inspect local runtime path health without touching live transports.",
            "parameters": _object_parameters({}),
        },
        "memory_warehouse_search": {
            "description": "Search the local memory warehouse text artifacts.",
            "parameters": _object_parameters({"query": _QUERY_PROPERTY, "max_results": _MAX_RESULTS_PROPERTY}, ["query"]),
        },
        "doc_lookup": {
            "description": "Search docs/*.md for a plain text query.",
            "parameters": _object_parameters({"query": _QUERY_PROPERTY, "max_results": _MAX_RESULTS_PROPERTY}, ["query"]),
        },
        "artifact_list": {
            "description": "List local artifact directories and files.",
            "parameters": _object_parameters({"path": _PATH_PROPERTY, "max_results": _MAX_RESULTS_PROPERTY}),
        },
        "env_read": {
            "description": "Report whether named environment variables are set; secret-like values remain redacted.",
            "parameters": _object_parameters(
                {
                    "names": {
                        "type": "array",
                        "items": {"type": "string"},
                        "minItems": 1,
                        "maxItems": 20,
                    },
                    "include_values": {"type": "boolean"},
                },
                ["names"],
            ),
        },
        "dependency_check": {
            "description": "Inspect dependency manifest files such as pyproject.toml and requirements*.txt.",
            "parameters": _object_parameters({"max_results": _MAX_RESULTS_PROPERTY}),
        },
        "time_now": {
            "description": "Return current local and UTC time.",
            "parameters": _object_parameters({}),
        },
        "path_resolve": {
            "description": "Resolve a workspace path and report whether it remains inside the workspace.",
            "parameters": _object_parameters({"path": _PATH_PROPERTY}, ["path"]),
        },
        "workspace_snapshot": {
            "description": "Return bounded workspace file counts and top-level entries.",
            "parameters": _object_parameters({"path": _PATH_PROPERTY, "max_entries": _MAX_RESULTS_PROPERTY}),
        },
        "command_run": {
            "description": "Run a read-only allowlisted command. This is an alias of local_command.",
            "parameters": _object_parameters(
                {
                    "argv": _ARGV_PROPERTY,
                    "cwd": {"type": "string", "description": "Optional workspace-relative working directory."},
                    "timeout_seconds": {"type": "integer", "minimum": 1, "maximum": 60},
                },
                ["argv"],
            ),
        },
        "file_write": {
            "description": "Permissioned write of a bounded UTF-8 file inside the workspace.",
            "parameters": _object_parameters(
                {
                    "path": _PATH_PROPERTY,
                    "content": {"type": "string", "description": "File content."},
                    "create_dirs": {"type": "boolean"},
                },
                ["path", "content"],
            ),
        },
        "file_replace": {
            "description": "Permissioned exact text replacement inside one workspace file.",
            "parameters": _object_parameters(
                {
                    "path": _PATH_PROPERTY,
                    "old_text": {"type": "string", "description": "Exact text to replace.", "minLength": 1},
                    "new_text": {"type": "string", "description": "Replacement text."},
                },
                ["path", "old_text", "new_text"],
            ),
        },
        "file_append": {
            "description": "Permissioned append to a bounded UTF-8 file inside the workspace.",
            "parameters": _object_parameters(
                {
                    "path": _PATH_PROPERTY,
                    "content": {"type": "string", "description": "Text to append."},
                    "create_dirs": {"type": "boolean"},
                },
                ["path", "content"],
            ),
        },
        "note_append": {
            "description": "Permissioned append of a progress note under docs/agent_progress_notes.",
            "parameters": _object_parameters(
                {
                    "title": {"type": "string"},
                    "summary": {"type": "string"},
                    "category": {"type": "string"},
                },
                ["title", "summary"],
            ),
        },
        "git_stage": {
            "description": "Permissioned git add for validated workspace paths.",
            "parameters": _object_parameters(
                {
                    "paths": {
                        "type": "array",
                        "items": {"type": "string"},
                        "minItems": 1,
                        "maxItems": 40,
                    }
                },
                ["paths"],
            ),
        },
        "git_commit": {
            "description": "Permissioned git commit with a supplied message.",
            "parameters": _object_parameters({"message": {"type": "string", "minLength": 1}}, ["message"]),
        },
        "command_modify": {
            "description": "Run a modifying command only after an explicit host permission grant.",
            "parameters": _object_parameters(
                {
                    "argv": _ARGV_PROPERTY,
                    "cwd": {"type": "string", "description": "Optional workspace-relative working directory."},
                    "timeout_seconds": {"type": "integer", "minimum": 1, "maximum": 60},
                },
                ["argv"],
            ),
        },
    }
)

STAGE119_DEFAULT_TOOL_NAMES = tuple(TOOL_REGISTRY.keys())


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


def _coerce_dsml_parameter(raw_value: str, *, is_string: bool) -> Any:
    value = html.unescape(str(raw_value or "").strip())
    if is_string:
        return value
    if not value:
        return ""
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def _parse_embedded_dsml_tool_calls(content: Any) -> list[dict[str, Any]]:
    text = str(content or "")
    if "tool_calls" not in text or "invoke" not in text:
        return []
    calls: list[dict[str, Any]] = []
    for block in _DSML_TOOL_BLOCK_RE.finditer(text):
        block_body = str(block.group("body") or "")
        for invoke in _DSML_INVOKE_RE.finditer(block_body):
            name = html.unescape(str(invoke.group("name") or "")).strip()
            if not name:
                continue
            arguments: dict[str, Any] = {}
            invoke_body = str(invoke.group("body") or "")
            for parameter in _DSML_PARAMETER_RE.finditer(invoke_body):
                key = html.unescape(str(parameter.group("name") or "")).strip()
                if not key:
                    continue
                is_string = str(parameter.group("string") or "").strip().lower() == "true"
                arguments[key] = _coerce_dsml_parameter(str(parameter.group("value") or ""), is_string=is_string)
            calls.append(
                {
                    "id": f"dsml_{name}_{len(calls) + 1}",
                    "type": "function",
                    "function": {"name": name, "arguments": arguments},
                }
            )
    return calls


def strip_provider_tool_markup(content: Any) -> str:
    text = str(content or "")
    if "tool_calls" not in text:
        return text.strip()
    return _DSML_TOOL_BLOCK_RE.sub("", text).strip()


def _validate_arguments(name: str, arguments: dict[str, Any]) -> str:
    schema = dict(TOOL_REGISTRY.get(name, {}).get("parameters", {}))
    required = list(schema.get("required", []) or [])
    for key in required:
        if key not in arguments or str(arguments.get(key, "") or "").strip() == "":
            return f"missing_required:{key}"
    return ""


def _normalise_provider_tool_call(
    *,
    name: str,
    call_id: str,
    arguments: dict[str, Any],
    call_type: str = "function",
) -> dict[str, Any]:
    error = ""
    if name not in TOOL_REGISTRY:
        error = "unknown_tool"
    else:
        error = _validate_arguments(name, arguments)
    return {
        "id": call_id,
        "type": call_type or "function",
        "name": name,
        "arguments": arguments,
        "allowed": not bool(error),
        "status": "rejected" if error else "accepted",
        "error": error,
    }


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
        parsed_call = _normalise_provider_tool_call(
            name=name,
            call_id=call_id,
            arguments=arguments,
            call_type=str(item.get("type", "function") or "function"),
        )
        if argument_error:
            parsed_call["allowed"] = False
            parsed_call["status"] = "rejected"
            parsed_call["error"] = argument_error
        parsed.append(parsed_call)
    for index, call in enumerate(_parse_embedded_dsml_tool_calls(message.get("content", ""))):
        item = dict(call) if isinstance(call, dict) else {}
        function = item.get("function", {})
        function_payload = dict(function) if isinstance(function, dict) else {}
        name = str(function_payload.get("name", "") or "").strip()
        call_id = str(item.get("id", "") or f"dsml_tool_call_{index + 1}")
        arguments, argument_error = _parse_arguments(function_payload.get("arguments", {}))
        parsed_call = _normalise_provider_tool_call(
            name=name,
            call_id=call_id,
            arguments=arguments,
            call_type=str(item.get("type", "function") or "function"),
        )
        if argument_error:
            parsed_call["allowed"] = False
            parsed_call["status"] = "rejected"
            parsed_call["error"] = argument_error
        parsed.append(parsed_call)
    return parsed


def provider_tool_calls_for_message(tool_calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
    provider_calls: list[dict[str, Any]] = []
    for index, call in enumerate(list(tool_calls or [])):
        item = dict(call) if isinstance(call, dict) else {}
        arguments = item.get("arguments", {})
        if not isinstance(arguments, dict):
            arguments = {}
        provider_calls.append(
            {
                "id": str(item.get("id", "") or f"tool_call_{index + 1}"),
                "type": str(item.get("type", "function") or "function"),
                "function": {
                    "name": str(item.get("name", "") or ""),
                    "arguments": json.dumps(arguments, ensure_ascii=False, sort_keys=True),
                },
            }
        )
    return provider_calls
