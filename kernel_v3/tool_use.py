from __future__ import annotations

import json
import threading
from contextlib import contextmanager
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
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


class ToolAbortSignal:
    def __init__(self, *, signal_id: str) -> None:
        self.signal_id = signal_id
        self._event = threading.Event()
        self._reason = ""

    def request(self, reason: str) -> None:
        self._reason = str(reason or "abort_requested")
        self._event.set()

    def requested(self) -> bool:
        return self._event.is_set()

    @property
    def reason(self) -> str:
        return self._reason


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
    progress_channel_id: str | None = None
    abort_signal_id: str | None = None
    timeout_seconds: int | None = None

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
            "progress_channel_id": self.progress_channel_id,
            "abort_signal_id": self.abort_signal_id,
            "timeout_seconds": self.timeout_seconds,
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


@dataclass
class _TrackedExecution:
    item: Any
    is_concurrency_safe: bool
    status: str = "queued"
    future: Future[Any] | None = None
    outcome: Any | None = None
    completed_event_emitted: bool = False


class StreamingToolExecutor:
    """Evented single-agent tool executor.

    This is intentionally provider-independent. A future provider-streaming loop
    can feed items into the same executor as tool_use deltas arrive; the current
    deep loop feeds a completed assistant turn and still gets the same queued /
    started / completed event stream.
    """

    def __init__(
        self,
        *,
        emit_event: Callable[[ToolExecutionEvent], None] | None = None,
        max_concurrency: int = 10,
    ) -> None:
        self.emit_event = emit_event
        self.max_concurrency = max(1, int(max_concurrency or 1))
        self._incremental_items: list[_TrackedExecution] = []
        self._incremental_pool: ThreadPoolExecutor | None = None
        self._incremental_execute_one: Callable[[Any], Any] | None = None
        self._incremental_is_concurrency_safe: Callable[[Any], bool] | None = None
        self._incremental_cancel_pending_on_failure = False
        self._incremental_is_failed: Callable[[Any], bool] | None = None
        self._incremental_failure_cancels_siblings: Callable[[Any, Any], bool] | None = None
        self._incremental_cancel_one: Callable[[Any, str], Any] | None = None
        self._incremental_failure_seen = False
        self._discarded = False

    def execute_batches(
        self,
        items: list[Any],
        *,
        execute_one: Callable[[Any], Any],
        is_concurrency_safe: Callable[[Any], bool],
        cancel_pending_on_failure: bool = False,
        is_failed: Callable[[Any], bool] | None = None,
        failure_cancels_siblings: Callable[[Any, Any], bool] | None = None,
        cancel_one: Callable[[Any, str], Any] | None = None,
    ) -> list[Any]:
        self.begin_incremental(
            execute_one=execute_one,
            is_concurrency_safe=is_concurrency_safe,
            cancel_pending_on_failure=cancel_pending_on_failure,
            is_failed=is_failed,
            failure_cancels_siblings=failure_cancels_siblings,
            cancel_one=cancel_one,
        )
        try:
            for item in items:
                self.add_item(item)
            return self.finish_remaining()
        finally:
            self.close()

    def begin_incremental(
        self,
        *,
        execute_one: Callable[[Any], Any],
        is_concurrency_safe: Callable[[Any], bool],
        cancel_pending_on_failure: bool = False,
        is_failed: Callable[[Any], bool] | None = None,
        failure_cancels_siblings: Callable[[Any, Any], bool] | None = None,
        cancel_one: Callable[[Any, str], Any] | None = None,
    ) -> None:
        self.close()
        self._discarded = False
        self._incremental_items = []
        self._incremental_execute_one = execute_one
        self._incremental_is_concurrency_safe = is_concurrency_safe
        self._incremental_cancel_pending_on_failure = bool(cancel_pending_on_failure)
        self._incremental_is_failed = is_failed
        self._incremental_failure_cancels_siblings = failure_cancels_siblings
        self._incremental_cancel_one = cancel_one
        self._incremental_failure_seen = False
        self._incremental_pool = ThreadPoolExecutor(max_workers=self.max_concurrency)

    def add_item(self, item: Any) -> None:
        if self._discarded:
            return
        if self._incremental_pool is None or self._incremental_is_concurrency_safe is None:
            raise RuntimeError("begin_incremental must be called before add_item")
        tracked = _TrackedExecution(
            item=item,
            is_concurrency_safe=bool(self._incremental_is_concurrency_safe(item)),
        )
        self._incremental_items.append(tracked)
        self._emit("queued", item)
        self._process_incremental_queue()

    def drain_completed(self) -> list[Any]:
        if self._discarded:
            return []
        self._process_incremental_queue()
        outcomes: list[Any] = []
        for tracked in self._incremental_items:
            if tracked.status == "yielded":
                continue
            self._refresh_incremental_completion(tracked, block=False)
            if tracked.status == "completed":
                tracked.status = "yielded"
                outcomes.append(tracked.outcome)
                continue
            if tracked.status == "running" and not tracked.is_concurrency_safe:
                break
        self._process_incremental_queue()
        return outcomes

    def finish_remaining(self) -> list[Any]:
        outcomes: list[Any] = []
        while not self._discarded and any(item.status != "yielded" for item in self._incremental_items):
            drained = self.drain_completed()
            if drained:
                outcomes.extend(drained)
                continue
            running = [item.future for item in self._incremental_items if item.status == "running" and item.future is not None]
            if running:
                wait(running, return_when=FIRST_COMPLETED)
                continue
            self._process_incremental_queue()
            queued = [item for item in self._incremental_items if item.status == "queued"]
            if not queued:
                break
        outcomes.extend(self.drain_completed())
        return outcomes

    def discard(self) -> None:
        self._discarded = True
        for tracked in self._incremental_items:
            if tracked.status == "queued":
                tracked.status = "yielded"
            elif tracked.status == "running" and tracked.future is not None:
                tracked.future.cancel()
        self.close()

    def close(self) -> None:
        if self._incremental_pool is not None:
            self._incremental_pool.shutdown(wait=False, cancel_futures=True)
            self._incremental_pool = None

    def _execute_with_started_event(self, item: Any, execute_one: Callable[[Any], Any]) -> Any:
        self._emit("started", item)
        return execute_one(item)

    def _process_incremental_queue(self) -> None:
        if self._discarded:
            return
        if self._incremental_pool is None or self._incremental_execute_one is None:
            return
        for tracked in self._incremental_items:
            if tracked.status == "running":
                self._refresh_incremental_completion(tracked, block=False)
        for tracked in self._incremental_items:
            if tracked.status != "queued":
                continue
            if self._incremental_failure_seen and self._incremental_cancel_pending_on_failure:
                tracked.outcome = _cancelled_outcome(tracked.item, self._incremental_cancel_one, "sibling_tool_failed")
                tracked.status = "completed"
                self._emit("cancelled", tracked.item, outcome=tracked.outcome)
                continue
            if not self._can_start_incremental(tracked):
                if not tracked.is_concurrency_safe:
                    break
                continue
            tracked.status = "running"
            tracked.future = self._incremental_pool.submit(
                self._execute_with_started_event,
                tracked.item,
                self._incremental_execute_one,
            )

    def _can_start_incremental(self, tracked: _TrackedExecution) -> bool:
        running = [item for item in self._incremental_items if item.status == "running"]
        if len(running) >= self.max_concurrency:
            return False
        if not running:
            return True
        return tracked.is_concurrency_safe and all(item.is_concurrency_safe for item in running)

    def _refresh_incremental_completion(self, tracked: _TrackedExecution, *, block: bool) -> None:
        if tracked.status != "running" or tracked.future is None:
            return
        if not block and not tracked.future.done():
            return
        tracked.outcome = tracked.future.result()
        tracked.status = "completed"
        if not tracked.completed_event_emitted:
            self._emit("completed", tracked.item, outcome=tracked.outcome)
            tracked.completed_event_emitted = True
        if _outcome_cancels_siblings(
            tracked.item,
            tracked.outcome,
            cancel_pending_on_failure=self._incremental_cancel_pending_on_failure,
            is_failed=self._incremental_is_failed,
            failure_cancels_siblings=self._incremental_failure_cancels_siblings,
        ):
            self._incremental_failure_seen = True

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


_TOOL_CONTROL_LOCK = threading.RLock()
_PROGRESS_CHANNELS: dict[str, Callable[[ToolExecutionEvent], None]] = {}
_ABORT_SIGNALS: dict[str, ToolAbortSignal] = {}


@contextmanager
def tool_execution_control(
    *,
    progress_channel_id: str,
    abort_signal: ToolAbortSignal,
    emit_event: Callable[[ToolExecutionEvent], None],
):
    with _TOOL_CONTROL_LOCK:
        _PROGRESS_CHANNELS[progress_channel_id] = emit_event
        _ABORT_SIGNALS[abort_signal.signal_id] = abort_signal
    try:
        yield
    finally:
        with _TOOL_CONTROL_LOCK:
            _PROGRESS_CHANNELS.pop(progress_channel_id, None)
            _ABORT_SIGNALS.pop(abort_signal.signal_id, None)


def emit_tool_progress(payload_or_context: object, *, status: str = "running", detail: JsonObject | None = None) -> bool:
    context = _host_context(payload_or_context)
    channel_id = str(context.get("progress_channel_id") or "")
    if not channel_id:
        return False
    with _TOOL_CONTROL_LOCK:
        emit = _PROGRESS_CHANNELS.get(channel_id)
    if emit is None:
        return False
    emit(
        ToolExecutionEvent(
            event_type="progress",
            tool_call_id=str(context.get("tool_call_id") or ""),
            action_id=str(context.get("action_id") or ""),
            tool_name=str(context.get("tool_name") or ""),
            status=status,
            detail=dict(detail or {}),
        )
    )
    return True


def tool_abort_requested(payload_or_context: object) -> bool:
    context = _host_context(payload_or_context)
    signal_id = str(context.get("abort_signal_id") or "")
    if not signal_id:
        return False
    with _TOOL_CONTROL_LOCK:
        signal = _ABORT_SIGNALS.get(signal_id)
    return bool(signal is not None and signal.requested())


def tool_abort_reason(payload_or_context: object) -> str:
    context = _host_context(payload_or_context)
    signal_id = str(context.get("abort_signal_id") or "")
    if not signal_id:
        return ""
    with _TOOL_CONTROL_LOCK:
        signal = _ABORT_SIGNALS.get(signal_id)
    return signal.reason if signal is not None else ""


def _host_context(payload_or_context: object) -> JsonObject:
    if not isinstance(payload_or_context, dict):
        return {}
    if payload_or_context.get("schema") == TOOL_USE_CONTEXT_SCHEMA:
        return dict(payload_or_context)
    context = payload_or_context.get("_host_context")
    return dict(context) if isinstance(context, dict) else {}


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
        selected_names = _selected_tool_names_from_query(query)
        names = _ordered_unique([*selected_names, *_string_list(action.payload.get("tool_names"))])
        limit = _positive_int(action.payload.get("max_results"), default=12, maximum=50)
        query_mode = "select" if selected_names else "explicit_names" if names and not query else "keyword"
        matches = _discover_tools(
            manifests,
            query="" if selected_names else query,
            side_effect_class=side_effect,
            tool_names=names,
            limit=max(limit, len(names)) if names else limit,
        )
        matched_names = {str(item.get("name") or "") for item in matches if isinstance(item, dict)}
        missing_names = [name for name in names if name not in matched_names]
        return Observation(
            observation_id=f"obs-{action.action_id}",
            run_id="",
            kind="tool_discovery_result",
            status="ok",
            source=f"tool:{TOOL_DISCOVERY_NAME}",
            content={
                "schema": TOOL_DISCOVERY_SCHEMA,
                "query": query,
                "query_mode": query_mode,
                "side_effect_class": side_effect,
                "requested_tool_names": names,
                "matched_tool_names": [str(item.get("name") or "") for item in matches if isinstance(item, dict)],
                "missing_tool_names": missing_names,
                "matched_count": len(matches),
                "tools": matches,
                "loading_protocol": "Use query='select:tool.name' for exact loading; then call returned tools[].name.",
                "host_boundary": (
                    "tool.discovery exposes allowed host tool contracts; host still validates every call."
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
                    "description": "Optional natural-language query, or select:tool.a,tool.b for exact tool loading.",
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
    progress_channel_id: str | None = None,
    abort_signal_id: str | None = None,
    timeout_seconds: int | None = None,
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
        progress_channel_id=progress_channel_id,
        abort_signal_id=abort_signal_id,
        timeout_seconds=timeout_seconds,
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


def _outcome_cancels_siblings(
    item: Any,
    outcome: Any,
    *,
    cancel_pending_on_failure: bool,
    is_failed: Callable[[Any], bool] | None,
    failure_cancels_siblings: Callable[[Any, Any], bool] | None,
) -> bool:
    if not cancel_pending_on_failure or not _outcome_failed(outcome, is_failed):
        return False
    if failure_cancels_siblings is None:
        return True
    try:
        return bool(failure_cancels_siblings(item, outcome))
    except Exception:
        return True


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
    runtime = tool_runtime_spec_for_manifest(manifest).to_dict()
    return {
        "name": manifest.name,
        "description": manifest.description,
        "resource_kind": manifest.resource_kind,
        "operator_kind": manifest.operator_kind,
        "side_effect_class": manifest.side_effect_class,
        "permissions_required": list(manifest.permissions_required),
        "input_schema": input_schema,
        "runtime": {
            "concurrency_safe": runtime["concurrency_safe"],
            "read_only": runtime["read_only"],
            "destructive": runtime["destructive"],
            "open_world": runtime["open_world"],
            "interrupt_behavior": runtime["interrupt_behavior"],
            "max_result_size_chars": runtime["max_result_size_chars"],
            "should_defer": runtime["should_defer"],
            "always_load": runtime["always_load"],
            "timeout_seconds": runtime["timeout_seconds"],
        },
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


def _selected_tool_names_from_query(query: str) -> list[str]:
    text = str(query or "").strip()
    if not text.casefold().startswith("select:"):
        return []
    _, _, tail = text.partition(":")
    return _ordered_unique(part.strip() for part in tail.split(",") if part.strip())


def _ordered_unique(values: Iterable[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _positive_int(value: object, *, default: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(1, min(maximum, parsed))
