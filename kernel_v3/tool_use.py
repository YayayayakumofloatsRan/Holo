from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

from kernel_v3.context.artifacts import ArtifactStore
from kernel_v3.contracts import CandidateAction, JsonObject, Observation, PolicyDecision, ToolManifest
from kernel_v3.tool_runtime import tool_runtime_spec_for_action, tool_runtime_spec_for_manifest
from kernel_v3.tools import ToolRegistry


TOOL_DISCOVERY_NAME = "tool.discovery"
ARTIFACT_READ_NAME = "artifact.read"
TOOL_DISCOVERY_SCHEMA = "holo.kernel_v3.tool_discovery.v1"
ARTIFACT_READ_SCHEMA = "holo.kernel_v3.artifact_read.v1"
TOOL_USE_CONTEXT_SCHEMA = "holo.kernel_v3.tool_use_context.v1"
TOOL_EXECUTION_EVENT_SCHEMA = "holo.kernel_v3.tool_execution_event.v1"


@dataclass(frozen=True)
class ToolUseContext:
    task_id: str
    run_id: str
    step_id: str
    thread_id: str
    input_text: str
    tool_call_id: str
    action_id: str
    tool_name: str
    side_effect_class: str
    policy_reason: str
    allowed_tool_names: list[str]
    runtime_spec: JsonObject = field(default_factory=dict)

    def to_execution_context(self) -> JsonObject:
        return {
            "schema": TOOL_USE_CONTEXT_SCHEMA,
            "task_id": self.task_id,
            "run_id": self.run_id,
            "step_id": self.step_id,
            "thread_id": self.thread_id,
            "input_text": self.input_text,
            "tool_call_id": self.tool_call_id,
            "action_id": self.action_id,
            "tool_name": self.tool_name,
            "side_effect_class": self.side_effect_class,
            "policy_reason": self.policy_reason,
            "allowed_tool_names": list(self.allowed_tool_names),
            "runtime_spec": dict(self.runtime_spec),
        }


@dataclass(frozen=True)
class ToolExecutionEvent:
    event_type: str
    tool_call_id: str
    action_id: str
    tool_name: str
    status: str | None = None
    detail: JsonObject | None = None

    def to_dict(self) -> JsonObject:
        return {
            "schema": TOOL_EXECUTION_EVENT_SCHEMA,
            "event_type": self.event_type,
            "tool_call_id": self.tool_call_id,
            "action_id": self.action_id,
            "tool_name": self.tool_name,
            "status": self.status,
            "detail": dict(self.detail or {}),
        }


@dataclass(frozen=True)
class ToolResultProjection:
    preview: str
    preview_chars: int
    truncated: bool
    estimated_chars: int
    shape: JsonObject

    def to_dict(self) -> JsonObject:
        return {
            "preview": self.preview,
            "preview_chars": self.preview_chars,
            "truncated": self.truncated,
            "estimated_chars": self.estimated_chars,
            "shape": dict(self.shape),
        }


class StreamingToolExecutor:
    """Evented single-agent tool executor.

    This is intentionally provider-independent. A future provider-streaming loop
    can feed items into the same executor as tool_use deltas arrive; the current
    deep loop feeds a completed assistant turn and still gets the same queued /
    started / completed event stream.
    """

    def __init__(self, *, emit_event: Callable[[ToolExecutionEvent], None] | None = None) -> None:
        self.emit_event = emit_event

    def execute_batches(
        self,
        items: list[Any],
        *,
        execute_one: Callable[[Any], Any],
        is_concurrency_safe: Callable[[Any], bool],
        cancel_pending_on_failure: bool = False,
        is_failed: Callable[[Any], bool] | None = None,
        cancel_one: Callable[[Any, str], Any] | None = None,
    ) -> list[Any]:
        outcomes: list[Any] = []
        for batch in _partition_batches(items, is_concurrency_safe=is_concurrency_safe):
            for item in batch:
                self._emit("queued", item)
            if len(batch) > 1 and all(is_concurrency_safe(item) for item in batch):
                with ThreadPoolExecutor(max_workers=len(batch)) as pool:
                    futures = []
                    for item in batch:
                        self._emit("started", item)
                        futures.append((item, pool.submit(execute_one, item)))
                    batch_outcomes = []
                    failure_seen = False
                    for item, future in futures:
                        if failure_seen and cancel_pending_on_failure and future.cancel():
                            cancelled = _cancelled_outcome(item, cancel_one, "sibling_tool_failed")
                            self._emit("cancelled", item, outcome=cancelled)
                            batch_outcomes.append(cancelled)
                            continue
                        outcome = future.result()
                        self._emit("completed", item, outcome=outcome)
                        if cancel_pending_on_failure and _outcome_failed(outcome, is_failed):
                            failure_seen = True
                        batch_outcomes.append(outcome)
            else:
                batch_outcomes = []
                failure_seen = False
                for item in batch:
                    if failure_seen and cancel_pending_on_failure:
                        cancelled = _cancelled_outcome(item, cancel_one, "sibling_tool_failed")
                        self._emit("cancelled", item, outcome=cancelled)
                        batch_outcomes.append(cancelled)
                        continue
                    self._emit("started", item)
                    outcome = execute_one(item)
                    self._emit("completed", item, outcome=outcome)
                    if cancel_pending_on_failure and _outcome_failed(outcome, is_failed):
                        failure_seen = True
                    batch_outcomes.append(outcome)
            outcomes.extend(batch_outcomes)
        return outcomes

    def _emit(self, event_type: str, item: Any, *, outcome: Any | None = None) -> None:
        if self.emit_event is None:
            return
        action = getattr(item, "action", None)
        call = getattr(item, "call", None)
        observation = getattr(outcome, "observation", None)
        detail: JsonObject = {}
        if observation is not None:
            detail["observation_id"] = getattr(observation, "observation_id", "")
            detail["observation_kind"] = getattr(observation, "kind", "")
        self.emit_event(
            ToolExecutionEvent(
                event_type=event_type,
                tool_call_id=str(getattr(call, "tool_call_id", "")),
                action_id=str(getattr(action, "action_id", "")),
                tool_name=str(getattr(action, "name", "") or ""),
                status=str(getattr(observation, "status", "")) if observation is not None else None,
                detail=detail,
            )
        )


def register_tool_discovery(
    registry: ToolRegistry,
    *,
    allowed_tool_names: set[str] | None = None,
) -> ToolRegistry:
    allowed = set(allowed_tool_names or set())
    allowed.add(TOOL_DISCOVERY_NAME)

    def execute(action: CandidateAction) -> Observation:
        manifests = [
            manifest
            for manifest in registry.manifests()
            if manifest.name in allowed and manifest.name != TOOL_DISCOVERY_NAME
        ]
        query = str(action.payload.get("query") or "").strip()
        side_effect = str(action.payload.get("side_effect_class") or "").strip()
        names = _string_list(action.payload.get("tool_names"))
        limit = _positive_int(action.payload.get("max_results"), default=12, maximum=50)
        matches = _discover_tools(manifests, query=query, side_effect_class=side_effect, tool_names=names, limit=limit)
        return Observation(
            observation_id=f"obs-{action.action_id}",
            run_id="",
            kind="tool_discovery_result",
            status="ok",
            source=f"tool:{TOOL_DISCOVERY_NAME}",
            content={
                "schema": TOOL_DISCOVERY_SCHEMA,
                "query": query,
                "side_effect_class": side_effect,
                "requested_tool_names": names,
                "matched_count": len(matches),
                "tools": matches,
                "host_boundary": (
                    "tool.discovery only exposes host-registered tool contracts; "
                    "the model still chooses the next concrete tool call and the host still validates policy."
                ),
            },
            observed_at_ms=0,
            action_id=action.action_id,
            tool_call_id=None,
        )

    registry.register(
        TOOL_DISCOVERY_NAME,
        execute,
        manifest=ToolManifest(
            name=TOOL_DISCOVERY_NAME,
            version="1",
            resource_kind="tooling",
            operator_kind="discover",
            side_effect_class="read",
            permissions_required=[],
            enabled=True,
            description="Discover currently allowed tool contracts by query, side effect, or explicit names.",
            input_schema={
                "query": {
                    "type": "str",
                    "required": False,
                    "min_length": 1,
                    "description": "Optional natural-language or keyword query such as sec filings, calculator, table, workspace, memory.",
                },
                "side_effect_class": {
                    "type": "str",
                    "required": False,
                    "description": "Optional side-effect filter: none, read, network, write, shell, destructive.",
                },
                "tool_names": {
                    "type": "list[str]",
                    "required": False,
                    "description": "Optional exact tool names to inspect.",
                },
                "max_results": {"type": "int", "required": False, "min": 1, "max": 50},
            },
            runtime={
                "concurrency_safe": True,
                "read_only": True,
                "always_load": True,
                "max_result_size_chars": 20000,
                "result_persistence_policy": "never",
            },
        ),
    )
    return registry


def register_artifact_tools(
    registry: ToolRegistry,
    *,
    artifact_store: ArtifactStore,
) -> ToolRegistry:
    def execute(action: CandidateAction) -> Observation:
        artifact_id = str(action.payload.get("artifact_id") or "").strip()
        mode = str(action.payload.get("mode") or "preview").strip().casefold() or "preview"
        max_chars = _positive_int(action.payload.get("max_chars"), default=4000, maximum=20000)
        if not artifact_id:
            return _artifact_observation(action, "failed", {"reason": "missing_artifact_id"}, kind="artifact_read_result")
        ref = artifact_store.get(artifact_id)
        if ref is None:
            return _artifact_observation(
                action,
                "failed",
                {"schema": ARTIFACT_READ_SCHEMA, "artifact_id": artifact_id, "reason": "artifact_not_found"},
                kind="artifact_read_result",
            )
        ref_data = ref.to_dict()
        if mode not in {"preview", "read"}:
            mode = "preview"
        if mode == "read" and artifact_store.has_blob(artifact_id):
            payload = artifact_store.read_blob(
                artifact_id,
                record_access=True,
                access_context={
                    "tool": ARTIFACT_READ_NAME,
                    "action_id": action.action_id,
                    "artifact_id": artifact_id,
                    "mode": mode,
                },
            )
            text = payload.decode("utf-8", errors="replace") if isinstance(payload, bytes) else payload
            truncated = len(text) > max_chars
            return _artifact_observation(
                action,
                "ok",
                {
                    "schema": ARTIFACT_READ_SCHEMA,
                    "artifact": ref_data,
                    "mode": mode,
                    "text": text[: max(0, max_chars - 3)] + "..." if truncated else text,
                    "text_chars": len(text),
                    "truncated": truncated,
                    "host_boundary": "artifact.read returns bounded artifact text; semantic interpretation remains model-owned",
                },
                kind="artifact_read_result",
            )
        preview = artifact_store.preview(artifact_id, limit=max_chars) if artifact_store.has_blob(artifact_id) else {
            "artifact_id": artifact_id,
            "preview": str(ref.metadata.get("preview") or ""),
            "size_bytes": ref.metadata.get("size_bytes"),
            "redaction_status": ref.metadata.get("redaction_status"),
        }
        return _artifact_observation(
            action,
            "ok",
            {
                "schema": ARTIFACT_READ_SCHEMA,
                "artifact": ref_data,
                "mode": "preview",
                "preview": preview,
                "blob_available": artifact_store.has_blob(artifact_id),
                "host_boundary": "use mode=read only when the preview is insufficient and the artifact has a blob",
            },
            kind="artifact_read_result",
        )

    registry.register(
        ARTIFACT_READ_NAME,
        execute,
        manifest=ToolManifest(
            name=ARTIFACT_READ_NAME,
            version="1",
            resource_kind="artifact",
            operator_kind="read",
            side_effect_class="read",
            permissions_required=[],
            enabled=True,
            description="Read a bounded preview or bounded text body for a host-exposed artifact reference.",
            input_schema={
                "artifact_id": {
                    "type": "str",
                    "required": True,
                    "min_length": 1,
                    "description": "Artifact id from recent_observations, artifact_references, or tool results.",
                },
                "mode": {
                    "type": "str",
                    "required": False,
                    "description": "preview or read. Defaults to preview.",
                },
                "max_chars": {"type": "int", "required": False, "min": 1, "max": 20000},
            },
            runtime={
                "concurrency_safe": True,
                "read_only": True,
                "always_load": True,
                "max_result_size_chars": 24000,
                "result_persistence_policy": "never",
            },
        ),
    )
    return registry


def tool_use_context_for_action(
    *,
    task_id: str,
    run_id: str,
    step_id: str,
    thread_id: str,
    input_text: str,
    tool_call_id: str,
    action: CandidateAction,
    manifest: ToolManifest | None,
    policy_decision: PolicyDecision | None,
    allowed_tool_names: Iterable[str],
) -> ToolUseContext:
    side_effect = str(getattr(manifest, "side_effect_class", action.side_effect_class) or action.side_effect_class)
    runtime_spec = tool_runtime_spec_for_action(action, manifest).to_dict()
    return ToolUseContext(
        task_id=task_id,
        run_id=run_id,
        step_id=step_id,
        thread_id=thread_id,
        input_text=input_text,
        tool_call_id=tool_call_id,
        action_id=action.action_id,
        tool_name=str(action.name or ""),
        side_effect_class=side_effect,
        policy_reason=str(getattr(policy_decision, "reason", "") or ""),
        allowed_tool_names=sorted(str(name) for name in allowed_tool_names if str(name)),
        runtime_spec=runtime_spec,
    )


def _artifact_observation(action: CandidateAction, status: str, content: JsonObject, *, kind: str) -> Observation:
    return Observation(
        observation_id=f"obs-{action.action_id}",
        run_id="",
        kind=kind,
        status=status,
        source=f"tool:{ARTIFACT_READ_NAME}",
        content=content,
        observed_at_ms=0,
        action_id=action.action_id,
        tool_call_id=None,
    )


def project_tool_result_content(value: object, *, limit: int = 1200) -> ToolResultProjection:
    try:
        text = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    except TypeError:
        text = str(value)
    truncated = len(text) > limit
    preview = text if not truncated else text[: max(0, limit - 3)] + "..."
    return ToolResultProjection(
        preview=preview,
        preview_chars=len(preview),
        truncated=truncated,
        estimated_chars=len(text),
        shape=_value_shape(value),
    )


def _outcome_failed(outcome: Any, is_failed: Callable[[Any], bool] | None) -> bool:
    if is_failed is not None:
        return is_failed(outcome)
    observation = getattr(outcome, "observation", None)
    status = str(getattr(observation, "status", "") or "")
    return status not in {"", "ok"}


def _cancelled_outcome(item: Any, cancel_one: Callable[[Any, str], Any] | None, reason: str) -> Any:
    if cancel_one is not None:
        return cancel_one(item, reason)
    return None


def _partition_batches(items: list[Any], *, is_concurrency_safe: Callable[[Any], bool]) -> list[list[Any]]:
    batches: list[list[Any]] = []
    current: list[Any] = []
    for item in items:
        if is_concurrency_safe(item):
            current.append(item)
            continue
        if current:
            batches.append(current)
            current = []
        batches.append([item])
    if current:
        batches.append(current)
    return batches


def _value_shape(value: object) -> JsonObject:
    if isinstance(value, dict):
        keys = [str(key) for key in value.keys()]
        return {
            "type": "object",
            "key_count": len(keys),
            "keys": keys[:32],
        }
    if isinstance(value, list):
        item_types = []
        for item in value[:16]:
            item_type = _type_name(item)
            if item_type not in item_types:
                item_types.append(item_type)
        return {
            "type": "array",
            "length": len(value),
            "sample_item_types": item_types,
        }
    return {"type": _type_name(value)}


def _type_name(value: object) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        return "str"
    if isinstance(value, dict):
        return "object"
    if isinstance(value, list):
        return "array"
    return type(value).__name__


def _discover_tools(
    manifests: list[ToolManifest],
    *,
    query: str,
    side_effect_class: str,
    tool_names: list[str],
    limit: int,
) -> list[JsonObject]:
    query_terms = [term for term in query.casefold().replace("/", " ").replace(".", " ").split() if term]
    requested = set(tool_names)
    side_effect = side_effect_class.casefold()
    results: list[tuple[int, JsonObject]] = []
    for manifest in manifests:
        if requested and manifest.name not in requested:
            continue
        if side_effect and manifest.side_effect_class.casefold() != side_effect:
            continue
        haystack = _manifest_search_text(manifest)
        score = _match_score(haystack, manifest.name.casefold(), query_terms)
        if query_terms and score <= 0:
            continue
        results.append((score, _manifest_summary(manifest)))
    results.sort(key=lambda item: (-item[0], str(item[1].get("name") or "")))
    return [item for _, item in results[:limit]]


def _manifest_summary(manifest: ToolManifest) -> JsonObject:
    input_schema = manifest.input_schema if isinstance(manifest.input_schema, dict) else {}
    return {
        "name": manifest.name,
        "version": manifest.version,
        "description": manifest.description,
        "resource_kind": manifest.resource_kind,
        "operator_kind": manifest.operator_kind,
        "side_effect_class": manifest.side_effect_class,
        "permissions_required": list(manifest.permissions_required),
        "enabled": manifest.enabled,
        "input_schema": input_schema,
        "runtime": tool_runtime_spec_for_manifest(manifest).to_dict(),
        "input_keys": [str(key) for key in input_schema.keys() if not str(key).startswith("_")],
    }


def _manifest_search_text(manifest: ToolManifest) -> str:
    return " ".join(
        [
            manifest.name,
            manifest.description,
            manifest.resource_kind,
            manifest.operator_kind,
            manifest.side_effect_class,
            json.dumps(manifest.input_schema, ensure_ascii=False, sort_keys=True, default=str),
            json.dumps(manifest.runtime, ensure_ascii=False, sort_keys=True, default=str),
        ]
    ).casefold()


def _match_score(haystack: str, name: str, terms: list[str]) -> int:
    if not terms:
        return 1
    score = 0
    for term in terms:
        if term in name:
            score += 4
        elif term in haystack:
            score += 1
    return score


def _string_list(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _positive_int(value: object, *, default: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(1, min(maximum, parsed))
