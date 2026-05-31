from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable

from kernel_v3.context.artifacts import ArtifactStore
from kernel_v3.contracts import ArtifactRef, CandidateAction, JsonObject, Observation, PolicyDecision, ToolManifest

WORKSPACE_PREVIEW_CHARS = 240


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
                input_schema={"url": "str"},
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
        self.executed_actions.append(action)
        raw = self._tools[tool_name].executor(_action_with_execution_context(action, execution_context))
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


def _fake_workspace_search(files: dict[str, str], *, artifact_store: ArtifactStore | None) -> ToolExecutor:
    def execute(action: CandidateAction) -> Observation:
        query = str(action.payload.get("query", ""))
        matches = []
        artifacts: list[ArtifactRef] = []
        for path, text in files.items():
            if query.lower() not in text.lower() and query.lower() not in path.lower():
                continue
            artifact = _workspace_payload_artifact(
                artifact_store=artifact_store,
                kind="workspace_search_match",
                path=path,
                text=text,
            )
            artifacts.append(artifact)
            matches.append(_workspace_text_payload(path=path, text=text, artifact=artifact))
        return ToolResult(observation=_tool_observation(action, "ok", {"matches": matches}), artifact_refs=artifacts)

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


def _fake_blocked_external_write(action: CandidateAction) -> Observation:
    return _tool_observation(action, "blocked", {"reason": "external_write_blocked_in_fake_tool"})


class _Workspace:
    def __init__(self, root: Path | str, *, artifact_store: ArtifactStore | None = None) -> None:
        self.root = Path(root).resolve()
        self.artifact_store = artifact_store

    def search(self, action: CandidateAction) -> ToolResult:
        query = str(action.payload.get("query", ""))
        matches: list[JsonObject] = []
        artifacts: list[ArtifactRef] = []
        for path in sorted(self.root.rglob("*")):
            if not path.is_file():
                continue
            rel = path.relative_to(self.root).as_posix()
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            if query.lower() in text.lower() or query.lower() in rel.lower():
                artifact = _workspace_payload_artifact(
                    artifact_store=self.artifact_store,
                    kind="workspace_search_match",
                    path=rel,
                    text=text,
                )
                artifacts.append(artifact)
                matches.append(_workspace_text_payload(path=rel, text=text, artifact=artifact))
        return ToolResult(observation=_tool_observation(action, "ok", {"matches": matches}), artifact_refs=artifacts)

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
        return _tool_result(action, "ok", {"path": rel, "bytes": len(text.encode("utf-8"))})

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


def _preview_text(text: str, limit: int) -> str:
    normalized = " ".join(text.split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: max(0, limit - 3)] + "..."
