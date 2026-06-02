from __future__ import annotations

import hashlib
import json
from datetime import datetime
import subprocess
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from kernel_v3.context.artifacts import ArtifactStore
from kernel_v3.contracts import ArtifactRef, CandidateAction, JsonObject, Observation, PolicyDecision, ToolManifest

WORKSPACE_PREVIEW_CHARS = 240
WORKSPACE_SEARCH_MAX_MATCHES = 20
WORKSPACE_SEARCH_SKIP_DIRS = {
    ".git",
    ".holo_runtime",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "node_modules",
}


@dataclass(frozen=True)
class ToolResult:
    observation: Observation
    artifact_refs: list[ArtifactRef]


ToolExecutor = Callable[[CandidateAction], Observation | ToolResult]


@dataclass(frozen=True)
class ToolSpec:
    manifest: ToolManifest
    executor: ToolExecutor

    @property
    def name(self) -> str:
        return self.manifest.name


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}
        self.executed_actions: list[CandidateAction] = []

    @classmethod
    def with_builtin_respond(cls) -> "ToolRegistry":
        registry = cls()
        registry.register("__respond__", _execute_respond, manifest=_manifest("__respond__", "host", "respond", "none"))
        registry.register("__ask_user__", _execute_ask_user, manifest=_manifest("__ask_user__", "host", "ask_user", "none"))
        registry.register("system.time", _execute_system_time, manifest=_system_time_manifest())
        return registry

    @classmethod
    def with_fake_workspace_tools(
        cls,
        *,
        files: dict[str, str] | None = None,
        artifact_store: ArtifactStore | None = None,
    ) -> "ToolRegistry":
        registry = cls.with_builtin_respond()
        fake_files = dict(files or {})
        registry.register(
            "workspace.search",
            _fake_workspace_search(fake_files, artifact_store=artifact_store),
            manifest=_workspace_manifest("workspace.search", "search", "read"),
        )
        registry.register(
            "file.read",
            _fake_file_read(fake_files, artifact_store=artifact_store),
            manifest=_workspace_manifest("file.read", "read", "read"),
        )
        registry.register(
            "workspace.write",
            _fake_workspace_write(fake_files, artifact_store=artifact_store),
            manifest=_workspace_manifest("workspace.write", "write", "write"),
        )
        registry.register(
            "blocked_external_write",
            _fake_blocked_external_write,
            manifest=_manifest(
                "blocked_external_write",
                "external",
                "write",
                "destructive",
                permissions_required=["external:write"],
            ),
        )
        return registry

    @classmethod
    def with_permissioned_workspace(
        cls,
        *,
        root: Path | str,
        shell_allowed_executables: set[str] | None = None,
        artifact_store: ArtifactStore | None = None,
    ) -> "ToolRegistry":
        registry = cls.with_builtin_respond()
        workspace = _Workspace(root, artifact_store=artifact_store)
        registry.register("workspace.search", workspace.search, manifest=_workspace_manifest("workspace.search", "search", "read"))
        registry.register("file.read", workspace.read, manifest=_workspace_manifest("file.read", "read", "read"))
        registry.register("workspace.write", workspace.write, manifest=_workspace_manifest("workspace.write", "write", "write"))
        registry.register(
            "shell.exec",
            _ShellExecutor(workspace.root, shell_allowed_executables or set()).execute,
            manifest=_manifest(
                "shell.exec",
                "shell",
                "exec",
                "shell",
                permissions_required=["shell:exec"],
                input_schema={"argv": "list[str]"},
            ),
        )
        registry.register(
            "network.fetch",
            _execute_network_contract,
            manifest=_manifest(
                "network.fetch",
                "network",
                "fetch",
                "network",
                permissions_required=["network:fetch"],
                enabled=False,
                input_schema={"url": {"type": "str", "required": True, "min_length": 1}},
            ),
        )
        return registry

    def register(
        self,
        name: str,
        executor: ToolExecutor,
        *,
        manifest: ToolManifest | None = None,
    ) -> None:
        self._tools[name] = ToolSpec(
            manifest=manifest or _manifest(name, "custom", "execute", "read"),
            executor=executor,
        )

    def manifests(self) -> list[ToolManifest]:
        return [spec.manifest for spec in self._tools.values()]

    def manifest_for_action(self, action: CandidateAction) -> ToolManifest | None:
        tool_name = _tool_name_for_action(action)
        if tool_name is None:
            return None
        spec = self._tools.get(tool_name)
        return spec.manifest if spec is not None else None

    def execute(self, action: CandidateAction) -> Observation:
        return self.execute_with_artifacts(action).observation

    def execute_with_artifacts(
        self,
        action: CandidateAction,
        *,
        policy_decision: PolicyDecision | None = None,
        execution_context: JsonObject | None = None,
    ) -> ToolResult:
        tool_name = _tool_name_for_action(action)
        if tool_name is None or tool_name not in self._tools:
            return _tool_result(
                action,
                "blocked",
                {"reason": "unregistered_tool", "tool": tool_name or ""},
                kind="policy_block",
            )
        manifest = self._tools[tool_name].manifest
        if _requires_policy_decision(action) and policy_decision is None:
            return _tool_result(
                action,
                "blocked",
                {
                    "reason": "policy_decision_required",
                    "tool": tool_name,
                    "side_effect_class": manifest.side_effect_class,
                },
                kind="policy_block",
            )
        if policy_decision is not None and policy_decision.action_id != action.action_id:
            return _tool_result(
                action,
                "blocked",
                {
                    "reason": "policy_decision_action_mismatch",
                    "tool": tool_name,
                    "policy_action_id": policy_decision.action_id,
                    "action_id": action.action_id,
                },
                kind="policy_block",
            )
        if policy_decision is not None:
            binding_error = _policy_binding_error(
                policy_decision,
                tool_name=tool_name,
                manifest=manifest,
                execution_context=execution_context,
            )
            if binding_error is not None:
                return _tool_result(action, "blocked", binding_error, kind="policy_block")
        if policy_decision is not None and not policy_decision.allowed:
            return _tool_result(
                action,
                "blocked",
                {"reason": policy_decision.reason, "tool": tool_name},
                kind="policy_block",
            )
        if not manifest.enabled:
            return _tool_result(
                action,
                "blocked",
                {"reason": "tool_disabled", "tool": tool_name},
                kind="policy_block",
            )
        canonical_payload, schema_error = _canonical_payload(action.payload, manifest.input_schema)
        if schema_error is not None:
            return _tool_result(
                action,
                "blocked",
                {"reason": "invalid_tool_payload", "tool": tool_name, "error": schema_error},
                kind="policy_block",
            )
        executable_action = replace(action, payload=canonical_payload)
        self.executed_actions.append(executable_action)
        try:
            raw = self._tools[tool_name].executor(_action_with_execution_context(executable_action, execution_context))
        except Exception as exc:
            return _tool_result(
                executable_action,
                "failed",
                {
                    "error": "tool_execution_failed",
                    "tool": tool_name,
                    "error_type": type(exc).__name__,
                },
                kind="tool_result",
            )
        result = raw if isinstance(raw, ToolResult) else _result_from_observation(raw)
        if result.artifact_refs:
            return result
        return ToolResult(
            observation=result.observation,
            artifact_refs=[_artifact_for_observation(result.observation)],
        )


def _tool_name_for_action(action: CandidateAction) -> str | None:
    if action.kind == "respond":
        return "__respond__"
    if action.kind == "ask_user":
        return "__ask_user__"
    return action.name


def _action_with_execution_context(
    action: CandidateAction,
    execution_context: JsonObject | None,
) -> CandidateAction:
    if not execution_context or action.kind != "tool":
        return action
    return replace(
        action,
        payload={**action.payload, "_host_context": dict(execution_context)},
    )


def _requires_policy_decision(action: CandidateAction) -> bool:
    return action.kind == "tool"


def _policy_binding_error(
    policy_decision: PolicyDecision,
    *,
    tool_name: str,
    manifest: ToolManifest,
    execution_context: JsonObject | None,
) -> JsonObject | None:
    constraints = policy_decision.constraints
    constrained_tool = constraints.get("tool_name")
    if constrained_tool != tool_name:
        return {
            "reason": "policy_decision_tool_mismatch",
            "tool": tool_name,
            "policy_tool": constrained_tool if isinstance(constrained_tool, str) else "",
        }
    constrained_side_effect = constraints.get("side_effect_class")
    if constrained_side_effect != manifest.side_effect_class:
        return {
            "reason": "policy_decision_side_effect_mismatch",
            "tool": tool_name,
            "side_effect_class": manifest.side_effect_class,
            "policy_side_effect_class": constrained_side_effect if isinstance(constrained_side_effect, str) else "",
        }
    expected_run_id = (execution_context or {}).get("run_id")
    if isinstance(expected_run_id, str) and expected_run_id and policy_decision.run_id != expected_run_id:
        return {
            "reason": "policy_decision_run_mismatch",
            "tool": tool_name,
            "policy_run_id": policy_decision.run_id,
            "run_id": expected_run_id,
        }
    return None


def _manifest(
    name: str,
    resource_kind: str,
    operator_kind: str,
    side_effect_class: str,
    *,
    permissions_required: list[str] | None = None,
    enabled: bool = True,
    input_schema: JsonObject | None = None,
) -> ToolManifest:
    return ToolManifest(
        name=name,
        version="1",
        resource_kind=resource_kind,
        operator_kind=operator_kind,
        side_effect_class=side_effect_class,
        permissions_required=list(permissions_required or []),
        enabled=enabled,
        description=f"{resource_kind}.{operator_kind}",
        input_schema=input_schema or {},
    )


def _workspace_manifest(name: str, operator_kind: str, side_effect_class: str) -> ToolManifest:
    permissions = ["workspace:read"] if side_effect_class == "read" else ["workspace:write"]
    return _manifest(
        name,
        "workspace",
        operator_kind,
        side_effect_class,
        permissions_required=permissions,
        input_schema=_workspace_input_schema(name),
    )


def _workspace_input_schema(name: str) -> JsonObject:
    if name == "workspace.search":
        return {
            "query": {
                "type": "str",
                "required": True,
                "min_length": 1,
                "aliases": ["path"],
                "description": "Non-empty search query. If a target file path is known, use it as query.",
            },
            "max_matches": {"type": "int", "required": False, "min": 1, "max": WORKSPACE_SEARCH_MAX_MATCHES},
        }
    if name == "file.read":
        return {
            "path": {
                "type": "str",
                "required": True,
                "min_length": 1,
                "description": "Workspace-relative file path.",
            }
        }
    if name == "workspace.write":
        return {
            "path": {
                "type": "str",
                "required": True,
                "min_length": 1,
                "description": "Workspace-relative file path. Absolute paths and parent-directory traversal are rejected.",
            },
            "text": {
                "type": "str",
                "required": True,
                "preserve_whitespace": True,
                "journal": "preview_hash",
                "preview_chars": WORKSPACE_PREVIEW_CHARS,
                "description": "Complete UTF-8 file body to write. Journal stores only preview/hash metadata.",
            },
        }
    return {}


def _system_time_manifest() -> ToolManifest:
    return _manifest(
        "system.time",
        "system",
        "time",
        "read",
        input_schema={
            "timezone": {
                "type": "str",
                "required": False,
                "min_length": 1,
                "description": "IANA timezone name such as Asia/Shanghai or UTC. Defaults to the host local timezone.",
            }
        },
    )


def _execute_respond(action: CandidateAction) -> Observation:
    return Observation(
        observation_id=f"obs-{action.action_id}",
        run_id="",
        kind="respond_result",
        status="ok",
        source="respond",
        content={"text": _response_text(action.payload, fallback=action.description)},
        observed_at_ms=0,
        action_id=action.action_id,
        tool_call_id=None,
    )


def _execute_ask_user(action: CandidateAction) -> Observation:
    return Observation(
        observation_id=f"obs-{action.action_id}",
        run_id="",
        kind="ask_user",
        status="needs_user_input",
        source="ask_user",
        content={"question": _question_text(action.payload, fallback=action.description)},
        observed_at_ms=0,
        action_id=action.action_id,
        tool_call_id=None,
    )


def _execute_system_time(action: CandidateAction) -> Observation:
    requested_timezone = action.payload.get("timezone")
    timezone_name = str(requested_timezone).strip() if isinstance(requested_timezone, str) else ""
    tz = _timezone(timezone_name)
    now = datetime.now(tz).replace(microsecond=0)
    return _tool_observation(
        action,
        "ok",
        {
            "timezone": timezone_name or str(now.tzinfo or "local"),
            "iso8601": now.isoformat(),
            "date": now.strftime("%Y-%m-%d"),
            "time": now.strftime("%H:%M:%S"),
            "utc_offset": now.strftime("%z"),
            "unix_ms": int(now.timestamp() * 1000),
        },
        kind="system_time",
    )


def _timezone(timezone_name: str):
    if not timezone_name:
        return datetime.now().astimezone().tzinfo
    try:
        return ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        return ZoneInfo("UTC")


def _response_text(payload: JsonObject, *, fallback: str = "") -> str:
    for key in ("text", "answer", "message", "summary", "response", "content"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value
    value = payload.get("cwd")
    if isinstance(value, str) and value.strip():
        return value
    user_payload = _user_payload(payload)
    if user_payload:
        return json.dumps(user_payload, ensure_ascii=False, sort_keys=True)
    if fallback.strip():
        return fallback
    return ""


def _question_text(payload: JsonObject, *, fallback: str = "") -> str:
    for key in ("question", "prompt", "text", "message", "content"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value
    user_payload = _user_payload(payload)
    if user_payload:
        return json.dumps(user_payload, ensure_ascii=False, sort_keys=True)
    if fallback.strip():
        return fallback
    return ""


def _user_payload(payload: JsonObject) -> JsonObject:
    return {key: value for key, value in payload.items() if not str(key).startswith("_host_")}


def _canonical_payload(payload: JsonObject, schema: JsonObject) -> tuple[JsonObject, str | None]:
    if not schema:
        return dict(payload), None
    canonical = dict(payload)
    for key, raw_spec in schema.items():
        if str(key).startswith("_") or key in {"network_fetch_cost_field", "default_network_fetch_cost"}:
            continue
        spec = _schema_spec(raw_spec)
        value = canonical.get(key)
        if value is None:
            for alias in spec["aliases"]:
                if alias in canonical and canonical[alias] is not None:
                    value = canonical[alias]
                    break
        if value is None:
            if spec["required"]:
                return canonical, f"missing_required_field:{key}"
            continue
        coerced, error = _coerce_schema_value(key, value, spec)
        if error is not None:
            return canonical, error
        canonical[key] = coerced
    return canonical, None


def _schema_spec(raw_spec: object) -> JsonObject:
    if isinstance(raw_spec, dict):
        aliases = raw_spec.get("aliases")
        return {
            "type": str(raw_spec.get("type", "object")),
            "required": bool(raw_spec.get("required", True)),
            "min_length": raw_spec.get("min_length"),
            "min": raw_spec.get("min"),
            "max": raw_spec.get("max"),
            "preserve_whitespace": bool(raw_spec.get("preserve_whitespace", False)),
            "aliases": [str(item) for item in aliases] if isinstance(aliases, list) else [],
        }
    text = str(raw_spec)
    return {
        "type": text.split()[0],
        "required": "optional" not in text,
        "min_length": None,
        "min": None,
        "max": None,
        "preserve_whitespace": False,
        "aliases": [],
    }


def _coerce_schema_value(key: str, value: object, spec: JsonObject) -> tuple[object, str | None]:
    expected = str(spec["type"])
    if expected == "str":
        if not isinstance(value, str):
            return value, f"invalid_field_type:{key}:str"
        parsed = value if bool(spec.get("preserve_whitespace")) else value.strip()
        min_length = _optional_int(spec.get("min_length"))
        if min_length is not None and len(parsed.strip() if bool(spec.get("preserve_whitespace")) else parsed) < min_length:
            return value, f"invalid_field_value:{key}:min_length"
        return parsed, None
    if expected == "int":
        try:
            parsed_int = int(value)
        except (TypeError, ValueError):
            return value, f"invalid_field_type:{key}:int"
        min_value = _optional_int(spec.get("min"))
        max_value = _optional_int(spec.get("max"))
        if min_value is not None:
            parsed_int = max(min_value, parsed_int)
        if max_value is not None:
            parsed_int = min(max_value, parsed_int)
        return parsed_int, None
    if expected in {"object", "dict"}:
        if not isinstance(value, dict):
            return value, f"invalid_field_type:{key}:object"
        return value, None
    if expected == "list[str]":
        if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
            return value, f"invalid_field_type:{key}:list[str]"
        return value, None
    if expected == "list":
        if not isinstance(value, list):
            return value, f"invalid_field_type:{key}:list"
        return value, None
    return value, None


def _optional_int(value: object) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _fake_workspace_search(files: dict[str, str], *, artifact_store: ArtifactStore | None) -> ToolExecutor:
    def execute(action: CandidateAction) -> Observation:
        query = str(action.payload.get("query", "")).strip()
        limit = _search_limit(action.payload.get("max_matches"))
        matches = []
        artifacts: list[ArtifactRef] = []
        for path, text in files.items():
            if query.lower() not in text.lower() and query.lower() not in path.lower():
                continue
            artifact = _workspace_search_artifact(
                artifact_store=artifact_store,
                path=path,
                text=text,
            )
            artifacts.append(artifact)
            matches.append(_workspace_text_payload(path=path, text=text, artifact=artifact))
            if len(matches) >= limit:
                break
        return ToolResult(observation=_tool_observation(action, "ok", {"query": query, "matches": matches}), artifact_refs=artifacts)

    return execute


def _fake_file_read(files: dict[str, str], *, artifact_store: ArtifactStore | None) -> ToolExecutor:
    def execute(action: CandidateAction) -> Observation:
        path = str(action.payload.get("path", ""))
        if path not in files:
            return _tool_observation(action, "failed", {"path": path, "error": "file_not_found"})
        text = files[path]
        artifact = _workspace_payload_artifact(
            artifact_store=artifact_store,
            kind="workspace_file_read",
            path=path,
            text=text,
        )
        return ToolResult(
            observation=_tool_observation(action, "ok", _workspace_text_payload(path=path, text=text, artifact=artifact)),
            artifact_refs=[artifact],
        )

    return execute


def _fake_workspace_write(files: dict[str, str], *, artifact_store: ArtifactStore | None) -> ToolExecutor:
    def execute(action: CandidateAction) -> ToolResult:
        path = str(action.payload.get("path", "")).strip()
        text = str(action.payload.get("text", ""))
        if _unsafe_workspace_path_value(path):
            return _tool_result(action, "blocked", {"path": path, "error": "path_outside_workspace"})
        files[path] = text
        artifact = _workspace_payload_artifact(
            artifact_store=artifact_store,
            kind="workspace_file_write",
            path=path,
            text=text,
        )
        return ToolResult(
            observation=_tool_observation(
                action,
                "ok",
                _workspace_write_payload(path=path, text=text, artifact=artifact),
            ),
            artifact_refs=[artifact],
        )

    return execute


def _fake_blocked_external_write(action: CandidateAction) -> Observation:
    return _tool_observation(action, "blocked", {"reason": "external_write_blocked_in_fake_tool"})


class _Workspace:
    def __init__(self, root: Path | str, *, artifact_store: ArtifactStore | None = None) -> None:
        self.root = Path(root).resolve()
        self.artifact_store = artifact_store

    def search(self, action: CandidateAction) -> ToolResult:
        query = str(action.payload.get("query", "")).strip()
        limit = _search_limit(action.payload.get("max_matches"))
        lowered_query = query.lower()
        matches: list[JsonObject] = []
        artifacts: list[ArtifactRef] = []
        for path in sorted(self.root.rglob("*")):
            rel_path = path.relative_to(self.root)
            if _skip_workspace_path(rel_path) or not path.is_file():
                continue
            rel = rel_path.as_posix()
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            if lowered_query in text.lower() or lowered_query in rel.lower():
                artifact = _workspace_search_artifact(
                    artifact_store=self.artifact_store,
                    path=rel,
                    text=text,
                )
                artifacts.append(artifact)
                matches.append(_workspace_text_payload(path=rel, text=text, artifact=artifact))
                if len(matches) >= limit:
                    break
        return ToolResult(observation=_tool_observation(action, "ok", {"query": query, "matches": matches}), artifact_refs=artifacts)

    def read(self, action: CandidateAction) -> ToolResult:
        rel = str(action.payload.get("path", ""))
        path = self._resolve(rel)
        if path is None or not path.is_file():
            return _tool_result(action, "failed", {"path": rel, "error": "file_not_found"})
        text = path.read_text(encoding="utf-8")
        artifact = _workspace_payload_artifact(
            artifact_store=self.artifact_store,
            kind="workspace_file_read",
            path=rel,
            text=text,
        )
        return ToolResult(
            observation=_tool_observation(action, "ok", _workspace_text_payload(path=rel, text=text, artifact=artifact)),
            artifact_refs=[artifact],
        )

    def write(self, action: CandidateAction) -> ToolResult:
        rel = str(action.payload.get("path", ""))
        text = str(action.payload.get("text", ""))
        path = self._resolve(rel)
        if path is None:
            return _tool_result(action, "blocked", {"path": rel, "error": "path_outside_workspace"})
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        artifact = _workspace_payload_artifact(
            artifact_store=self.artifact_store,
            kind="workspace_file_write",
            path=rel,
            text=text,
        )
        return ToolResult(
            observation=_tool_observation(
                action,
                "ok",
                _workspace_write_payload(path=rel, text=text, artifact=artifact),
            ),
            artifact_refs=[artifact],
        )

    def _resolve(self, rel: str) -> Path | None:
        candidate = (self.root / rel).resolve()
        try:
            candidate.relative_to(self.root)
        except ValueError:
            return None
        return candidate


class _ShellExecutor:
    def __init__(self, root: Path, allowed_executables: set[str]) -> None:
        self.root = root
        self.allowed_executables = set(allowed_executables)

    def execute(self, action: CandidateAction) -> ToolResult:
        argv = action.payload.get("argv", [])
        if not isinstance(argv, list) or not argv or not all(isinstance(arg, str) for arg in argv):
            return _tool_result(action, "failed", {"error": "argv_must_be_list_of_strings"})
        exe_name = Path(argv[0]).name
        if exe_name not in self.allowed_executables:
            return _tool_result(action, "blocked", {"argv": argv, "error": "executable_not_allowed"})
        completed = subprocess.run(
            argv,
            cwd=self.root,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=5,
            check=False,
        )
        return _tool_result(
            action,
            "ok" if completed.returncode == 0 else "failed",
            {
                "argv": argv,
                "exit_code": completed.returncode,
                "stdout": completed.stdout,
                "stderr": completed.stderr,
            },
        )


def _execute_network_contract(action: CandidateAction) -> ToolResult:
    return _tool_result(
        action,
        "not_implemented",
        {
            "url": action.payload.get("url", ""),
            "reason": "network_tool_contract_only_no_live_fetch",
        },
        kind="network_contract",
    )


def _tool_observation(action: CandidateAction, status: str, content: JsonObject, *, kind: str = "tool_result") -> Observation:
    return Observation(
        observation_id=f"obs-{action.action_id}",
        run_id="",
        kind=kind,
        status=status,
        source=f"tool:{action.name}",
        content=content,
        observed_at_ms=0,
        action_id=action.action_id,
        tool_call_id=None,
    )


def _tool_result(action: CandidateAction, status: str, content: JsonObject, *, kind: str = "tool_result") -> ToolResult:
    observation = _tool_observation(action, status, content, kind=kind)
    return ToolResult(observation=observation, artifact_refs=[_artifact_for_observation(observation)])


def _result_from_observation(observation: Observation) -> ToolResult:
    return ToolResult(observation=observation, artifact_refs=[_artifact_for_observation(observation)])


def _artifact_for_observation(observation: Observation) -> ArtifactRef:
    payload = observation.to_dict()
    return ArtifactRef(
        artifact_id=f"artifact-{observation.observation_id}",
        kind="observation_payload",
        uri=f"journal://observations/{observation.observation_id}",
        payload_hash=_payload_hash(payload),
        metadata={"observation_id": observation.observation_id, "source": observation.source},
    )


def _payload_hash(payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _workspace_payload_artifact(
    *,
    artifact_store: ArtifactStore | None,
    kind: str,
    path: str,
    text: str,
) -> ArtifactRef:
    payload_bytes = text.encode("utf-8")
    payload_hash = hashlib.sha256(payload_bytes).hexdigest()
    preview = _preview_text(text, WORKSPACE_PREVIEW_CHARS)
    metadata = {
        "path": path,
        "size_bytes": len(payload_bytes),
        "preview": preview,
        "redaction_status": "raw_body_in_artifact_store",
    }
    if artifact_store is not None:
        return artifact_store.write_blob(
            kind=kind,
            payload=text,
            mime_type="text/plain",
            metadata={"path": path},
            redaction_status="unredacted",
        )
    return ArtifactRef(
        artifact_id=f"artifact-workspace-{payload_hash[:16]}",
        kind=kind,
        uri=f"workspace://{path}",
        payload_hash=payload_hash,
        metadata=metadata,
    )


def _workspace_search_artifact(
    *,
    artifact_store: ArtifactStore | None,
    path: str,
    text: str,
) -> ArtifactRef:
    preview = _preview_text(text, WORKSPACE_PREVIEW_CHARS)
    payload_bytes = preview.encode("utf-8")
    payload_hash = hashlib.sha256(f"{path}\n{preview}".encode("utf-8")).hexdigest()
    metadata = {
        "path": path,
        "size_bytes": len(payload_bytes),
        "preview": preview,
        "full_size_bytes": len(text.encode("utf-8")),
        "redaction_status": "search_preview_only",
    }
    if artifact_store is not None:
        return artifact_store.write_blob(
            kind="workspace_search_match",
            payload=preview,
            mime_type="text/plain",
            metadata=metadata,
            redaction_status="search_preview_only",
        )
    return ArtifactRef(
        artifact_id=f"artifact-search-{payload_hash[:16]}",
        kind="workspace_search_match",
        uri=f"workspace://{path}",
        payload_hash=payload_hash,
        metadata=metadata,
    )


def _workspace_text_payload(*, path: str, text: str, artifact: ArtifactRef) -> JsonObject:
    size = artifact.metadata.get("size_bytes")
    preview = artifact.metadata.get("preview")
    return {
        "path": path,
        "text_preview": str(preview) if isinstance(preview, str) else _preview_text(text, WORKSPACE_PREVIEW_CHARS),
        "artifact_id": artifact.artifact_id,
        "payload_hash": artifact.payload_hash,
        "size_bytes": int(size) if isinstance(size, int) else len(text.encode("utf-8")),
    }


def _workspace_write_payload(*, path: str, text: str, artifact: ArtifactRef) -> JsonObject:
    return {
        "path": path,
        "bytes": len(text.encode("utf-8")),
        "text_preview": _preview_text(text, WORKSPACE_PREVIEW_CHARS),
        "artifact_id": artifact.artifact_id,
        "payload_hash": artifact.payload_hash,
    }


def _preview_text(text: str, limit: int) -> str:
    normalized = " ".join(text.split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: max(0, limit - 3)] + "..."


def _search_limit(value: object) -> int:
    parsed = _optional_int(value)
    if parsed is None:
        return WORKSPACE_SEARCH_MAX_MATCHES
    return max(1, min(WORKSPACE_SEARCH_MAX_MATCHES, parsed))


def _skip_workspace_path(path: Path) -> bool:
    return any(part in WORKSPACE_SEARCH_SKIP_DIRS for part in path.parts)


def _unsafe_workspace_path_value(path: str) -> bool:
    if not path.strip():
        return True
    parsed = Path(path)
    return parsed.is_absolute() or any(part == ".." for part in parsed.parts)
