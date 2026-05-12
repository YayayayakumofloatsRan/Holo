from __future__ import annotations

import json
import subprocess
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence


MCP_PROTOCOL_VERSION = "2025-11-25"
STAGE53_NAME = "stage53-mcp-upstream-tools"

UPSTREAM_BOUNDARY = {
    "wsl_kernel_authority": True,
    "upstream_results_are_observations": True,
    "upstream_server_decision_authority": False,
    "transport_decision_authority": False,
    "wechat_transport_used": False,
    "watcher_decision_authority": False,
    "self_memory_write_allowed": False,
    "policy_mutation_allowed": False,
    "shell_execution_via_mcp": False,
    "unbounded_loop_allowed": False,
}


class McpUpstreamError(RuntimeError):
    """Raised when an upstream MCP stdio server violates the bounded contract."""


class McpToolNotAllowedError(McpUpstreamError):
    """Raised before process launch when a requested MCP tool is not allowed."""


@dataclass(frozen=True, slots=True)
class McpUpstreamServerConfig:
    name: str
    command: Sequence[str]
    enabled: bool = True
    allowed_tools: tuple[str, ...] = ()
    cwd: str | None = None
    timeout_seconds: float = 30.0
    max_response_bytes: int = 1_000_000

    def __post_init__(self) -> None:
        normalized_name = _normalize_server_name(self.name)
        object.__setattr__(self, "name", normalized_name)
        if isinstance(self.command, str):
            raise ValueError(f"MCP server {normalized_name!r} command must be a non-empty argv sequence")
        if not self.command and self.enabled:
            raise ValueError(f"MCP server {normalized_name!r} command must be configured when enabled")
        normalized_command = tuple(str(part) for part in self.command)
        if any(not part for part in normalized_command):
            raise ValueError(f"MCP server {normalized_name!r} command argv entries must be non-empty strings")
        object.__setattr__(self, "command", normalized_command)
        object.__setattr__(
            self,
            "allowed_tools",
            tuple(str(item).strip() for item in self.allowed_tools if str(item).strip()),
        )
        if self.timeout_seconds <= 0:
            raise ValueError(f"MCP server {normalized_name!r} timeout_seconds must be positive")
        if self.max_response_bytes <= 0:
            raise ValueError(f"MCP server {normalized_name!r} max_response_bytes must be positive")

    def client(self) -> "McpStdioUpstreamClient":
        if not self.command:
            raise McpUpstreamError(f"MCP server {self.name!r} has no command configured")
        return McpStdioUpstreamClient(
            self.command,
            timeout_seconds=self.timeout_seconds,
            max_response_bytes=self.max_response_bytes,
            cwd=self.cwd,
        )

    def status(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "command": list(self.command),
            "allowed_tools": list(self.allowed_tools),
            "cwd": self.cwd,
            "timeout_seconds": self.timeout_seconds,
            "max_response_bytes": self.max_response_bytes,
            "transport": "stdio",
            "shell": False,
        }


@dataclass(slots=True)
class McpUpstreamRegistry:
    servers: dict[str, McpUpstreamServerConfig]

    def __post_init__(self) -> None:
        normalized: dict[str, McpUpstreamServerConfig] = {}
        for name, config in self.servers.items():
            key = _normalize_server_name(name)
            if key != config.name:
                config = McpUpstreamServerConfig(
                    name=key,
                    command=config.command,
                    enabled=config.enabled,
                    allowed_tools=config.allowed_tools,
                    cwd=config.cwd,
                    timeout_seconds=config.timeout_seconds,
                    max_response_bytes=config.max_response_bytes,
                )
            normalized[key] = config
        self.servers = normalized

    def enabled_server_names(self) -> list[str]:
        return [name for name, config in self.servers.items() if config.enabled]

    def status(self) -> dict[str, Any]:
        return {
            "stage": STAGE53_NAME,
            "protocol_version": MCP_PROTOCOL_VERSION,
            "transport": "stdio",
            "servers": {name: config.status() for name, config in self.servers.items()},
            "enabled_servers": self.enabled_server_names(),
            "boundary": dict(UPSTREAM_BOUNDARY),
        }


@dataclass(slots=True)
class McpStdioUpstreamClient:
    command: Sequence[str]
    timeout_seconds: float = 30.0
    max_response_bytes: int = 1_000_000
    cwd: str | None = None

    @property
    def uses_shell(self) -> bool:
        return False

    def __post_init__(self) -> None:
        if isinstance(self.command, str) or not self.command:
            raise ValueError("MCP upstream command must be a non-empty argv sequence")
        normalized = tuple(str(part) for part in self.command)
        if any(not part for part in normalized):
            raise ValueError("MCP upstream command argv entries must be non-empty strings")
        self.command = normalized
        if self.timeout_seconds <= 0:
            raise ValueError("MCP upstream timeout must be positive")
        if self.max_response_bytes <= 0:
            raise ValueError("MCP upstream max_response_bytes must be positive")

    def list_tools(self) -> dict[str, Any]:
        return self.call_method("tools/list")

    def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        if not str(name or "").strip():
            raise ValueError("MCP upstream tool name is required")
        return self.call_method("tools/call", {"name": str(name), "arguments": dict(arguments or {})})

    def read_resource(self, uri: str) -> dict[str, Any]:
        if not str(uri or "").strip():
            raise ValueError("MCP upstream resource uri is required")
        return self.call_method("resources/read", {"uri": str(uri)})

    def call_method(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        if not str(method or "").strip():
            raise ValueError("MCP upstream method is required")
        messages = [
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": MCP_PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": {"name": "holo-upstream-client", "version": STAGE53_NAME},
                },
            },
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": str(method), "params": dict(params or {})},
        ]
        input_text = "".join(json.dumps(message, ensure_ascii=False) + "\n" for message in messages)
        process = subprocess.Popen(
            list(self.command),
            cwd=self.cwd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            shell=False,
        )
        try:
            stdout, stderr = process.communicate(input=input_text, timeout=self.timeout_seconds)
        except subprocess.TimeoutExpired as exc:
            process.kill()
            process.communicate()
            raise McpUpstreamError(f"MCP upstream call timed out after {self.timeout_seconds:g}s") from exc
        total_bytes = len(stdout.encode("utf-8", errors="replace")) + len(stderr.encode("utf-8", errors="replace"))
        if total_bytes > self.max_response_bytes:
            raise McpUpstreamError("MCP upstream response exceeded max_response_bytes")
        responses = self._parse_responses(stdout)
        init = responses.get(1)
        target = responses.get(2)
        if not init:
            raise McpUpstreamError("MCP upstream did not answer initialize")
        if "error" in init:
            raise McpUpstreamError(f"MCP upstream initialize failed: {init['error']}")
        if not target:
            detail = stderr.strip() or "missing target response"
            raise McpUpstreamError(f"MCP upstream did not answer {method}: {detail}")
        if "error" in target:
            raise McpUpstreamError(f"MCP upstream {method} failed: {target['error']}")
        return dict(target.get("result", {}))

    @staticmethod
    def _parse_responses(stdout: str) -> dict[int, dict[str, Any]]:
        responses: dict[int, dict[str, Any]] = {}
        for line in stdout.splitlines():
            raw = line.strip()
            if not raw:
                continue
            try:
                message = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise McpUpstreamError("MCP upstream emitted non-JSON stdout") from exc
            if not isinstance(message, dict):
                raise McpUpstreamError("MCP upstream emitted non-object JSON-RPC message")
            message_id = message.get("id")
            if isinstance(message_id, int):
                responses[message_id] = message
        return responses


class McpUpstreamHub:
    def __init__(self, registry: McpUpstreamRegistry) -> None:
        self.registry = registry

    def status(self) -> dict[str, Any]:
        return self.registry.status()

    def list_tools(self) -> dict[str, Any]:
        tools: list[dict[str, Any]] = []
        errors: list[dict[str, str]] = []
        for server_name in self.registry.enabled_server_names():
            config = self.registry.servers[server_name]
            try:
                result = config.client().list_tools()
            except Exception as exc:  # noqa: BLE001 - discovery should degrade by server.
                errors.append({"server": server_name, "error": type(exc).__name__, "detail": str(exc)})
                continue
            for tool in list(result.get("tools", []) or []):
                if not isinstance(tool, dict):
                    continue
                tool_name = str(tool.get("name", "") or "").strip()
                if not tool_name:
                    continue
                if config.allowed_tools and tool_name not in config.allowed_tools:
                    continue
                descriptor = dict(tool)
                descriptor["server"] = server_name
                descriptor["name"] = tool_name
                descriptor["qualified_name"] = f"{server_name}.{tool_name}"
                tools.append(descriptor)
        return {
            "stage": STAGE53_NAME,
            "tools": tools,
            "errors": errors,
            "boundary": dict(UPSTREAM_BOUNDARY),
        }

    def call_tool(self, qualified_name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        server_name, tool_name = self._resolve_tool(qualified_name)
        config = self._enabled_server_config(server_name)
        if config.allowed_tools and tool_name not in config.allowed_tools:
            raise McpToolNotAllowedError(f"MCP tool {server_name}.{tool_name} is not in allowed_tools")
        result = config.client().call_tool(tool_name, dict(arguments or {}))
        return {
            "ok": not bool(result.get("isError", False)),
            "stage": STAGE53_NAME,
            "server": server_name,
            "tool": tool_name,
            "qualified_name": f"{server_name}.{tool_name}",
            "result": result,
            "boundary": dict(UPSTREAM_BOUNDARY),
        }

    def tool_allowed(self, qualified_name: str) -> tuple[bool, str]:
        try:
            server_name, tool_name = self._resolve_tool(qualified_name)
            config = self._enabled_server_config(server_name)
        except McpToolNotAllowedError as exc:
            return False, str(exc)
        if config.allowed_tools and tool_name not in config.allowed_tools:
            return False, f"MCP tool {server_name}.{tool_name} is not in allowed_tools"
        return True, "allowlisted_mcp_tool"

    def read_resource(self, server_name: str, uri: str) -> dict[str, Any]:
        server_key = _normalize_server_name(server_name)
        config = self._enabled_server_config(server_key)
        normalized_uri = str(uri or "").strip()
        if not normalized_uri:
            raise ValueError("MCP resource uri is required")
        result = config.client().read_resource(normalized_uri)
        return {
            "ok": True,
            "stage": STAGE53_NAME,
            "server": server_key,
            "uri": normalized_uri,
            "result": result,
            "boundary": dict(UPSTREAM_BOUNDARY),
        }

    def _enabled_server_config(self, server_name: str) -> McpUpstreamServerConfig:
        config = self.registry.servers.get(server_name)
        if config is None or not config.enabled:
            raise McpToolNotAllowedError(f"MCP server {server_name!r} is not configured or enabled")
        return config

    @staticmethod
    def _resolve_tool(qualified_name: str) -> tuple[str, str]:
        raw = str(qualified_name or "").strip()
        if "." in raw:
            server_name, tool_name = raw.split(".", 1)
        elif ":" in raw:
            server_name, tool_name = raw.split(":", 1)
        else:
            raise McpToolNotAllowedError("MCP tool name must be qualified as server.tool")
        server_key = _normalize_server_name(server_name)
        tool_key = str(tool_name or "").strip()
        if not tool_key:
            raise McpToolNotAllowedError("MCP tool name must include a tool after the server prefix")
        return server_key, tool_key


def load_mcp_server_registry(
    config_path: str | None = None,
    *,
    repo_root: str | Path | None = None,
) -> McpUpstreamRegistry:
    root = Path(repo_root or Path(__file__).resolve().parents[1]).resolve()
    chosen = Path(config_path).expanduser().resolve() if config_path else root / ".holo_host.toml"
    data: dict[str, Any] = {}
    if chosen.exists():
        data = tomllib.loads(chosen.read_text(encoding="utf-8"))
    raw_servers = data.get("mcp_servers", {})
    if not isinstance(raw_servers, dict):
        raw_servers = {}
    servers: dict[str, McpUpstreamServerConfig] = {}
    for raw_name, raw_payload in raw_servers.items():
        if not isinstance(raw_payload, dict):
            continue
        name = _normalize_server_name(str(raw_name))
        command = raw_payload.get("command", [])
        if isinstance(command, str):
            raise ValueError(f"MCP server {name!r} command must be an argv array, not a shell string")
        cwd = _resolve_optional_path(root, raw_payload.get("cwd"))
        servers[name] = McpUpstreamServerConfig(
            name=name,
            command=tuple(str(item) for item in list(command or [])),
            enabled=bool(raw_payload.get("enabled", True)),
            allowed_tools=tuple(str(item).strip() for item in raw_payload.get("allowed_tools", []) if str(item).strip()),
            cwd=cwd,
            timeout_seconds=float(raw_payload.get("timeout_seconds", 30.0) or 30.0),
            max_response_bytes=int(raw_payload.get("max_response_bytes", 1_000_000) or 1_000_000),
        )
    return McpUpstreamRegistry(servers=servers)


def build_mcp_upstream_hub(config_path: str | None = None, *, repo_root: str | Path | None = None) -> McpUpstreamHub:
    return McpUpstreamHub(load_mcp_server_registry(config_path=config_path, repo_root=repo_root))


def _normalize_server_name(name: str) -> str:
    normalized = str(name or "").strip()
    if not normalized:
        raise ValueError("MCP server name is required")
    allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-")
    if any(char not in allowed for char in normalized):
        raise ValueError(f"MCP server name {normalized!r} contains unsupported characters")
    return normalized


def _resolve_optional_path(root: Path, raw: Any) -> str | None:
    value = str(raw or "").strip()
    if not value:
        return None
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = root / path
    return str(path.resolve())
