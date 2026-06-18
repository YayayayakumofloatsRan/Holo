from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field

from kernel_v4.contracts import ChatMessage, JsonObject, LoopEvent, ToolMessage, stringify_tool_content
from kernel_v4.runtime import AbortController, ContextEdit, ToolLifecycleRecord, WorkflowObserver


DEFAULT_TOOL_RESULT_INLINE_CHARS = 50_000
TOOL_RESULT_PREVIEW_CHARS = 2_000


@dataclass
class ToolUseContext:
    """Thread-local state carried through one single-agent run.

    This mirrors the reference framework's ToolUseContext idea in Python:
    messages, in-progress tool IDs, artifacts, budget replacements, and
    host-visible events live here rather than in finance-specific state.
    """

    run_id: str
    thread_key: str = "default"
    messages: list[ChatMessage] = field(default_factory=list)
    abort_controller: AbortController = field(default_factory=AbortController)
    workflow: WorkflowObserver = field(default_factory=WorkflowObserver)
    in_progress_tool_use_ids: set[str] = field(default_factory=set)
    artifacts: dict[str, str] = field(default_factory=dict)
    tool_result_replacements: dict[str, str] = field(default_factory=dict)
    context_edits: list[ContextEdit] = field(default_factory=list)
    tool_lifecycle: dict[str, ToolLifecycleRecord] = field(default_factory=dict)
    metadata: JsonObject = field(default_factory=dict)

    def store_artifact(self, *, kind: str, content: str) -> str:
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        artifact_id = f"v4-{kind}-{digest[:16]}"
        self.artifacts[artifact_id] = content
        self.apply_edit(ContextEdit(operation="artifact.store", key=artifact_id, value={"kind": kind, "chars": len(content)}))
        return artifact_id

    def read_artifact(self, artifact_id: str) -> str:
        if artifact_id not in self.artifacts:
            raise KeyError(f"unknown v4 artifact: {artifact_id}")
        return self.artifacts[artifact_id]

    @property
    def abort_signal(self):
        return self.abort_controller.signal

    def emit_workflow(self, event: LoopEvent) -> None:
        self.workflow.emit(event)

    def apply_edit(self, edit: ContextEdit) -> JsonObject:
        result: JsonObject = {"operation": edit.operation, "applied": True}
        if edit.operation == "metadata.set":
            if not edit.key:
                raise ValueError("metadata.set requires key")
            self.metadata[edit.key] = edit.value
            result["key"] = edit.key
        elif edit.operation == "metadata.delete":
            if not edit.key:
                raise ValueError("metadata.delete requires key")
            self.metadata.pop(edit.key, None)
            result["key"] = edit.key
        elif edit.operation == "artifact.delete":
            if not edit.key:
                raise ValueError("artifact.delete requires key")
            self.artifacts.pop(edit.key, None)
            result["artifact_id"] = edit.key
        elif edit.operation == "message.append":
            if not isinstance(edit.value, ChatMessage):
                raise TypeError("message.append requires ChatMessage value")
            self.messages.append(edit.value)
            result["message_role"] = edit.value.role
        elif edit.operation == "artifact.store":
            result["artifact_id"] = edit.key or ""
        else:
            raise ValueError(f"unsupported context edit operation: {edit.operation}")
        self.context_edits.append(edit)
        return result

    def record_tool_lifecycle(
        self,
        *,
        tool_call_id: str,
        tool: str,
        status: str,
        turn_index: int,
        metadata: JsonObject | None = None,
    ) -> ToolLifecycleRecord:
        record = self.tool_lifecycle.get(tool_call_id)
        if record is None:
            record = ToolLifecycleRecord(tool_call_id=tool_call_id, tool=tool, status="queued")
            self.tool_lifecycle[tool_call_id] = record
        record.transition(status, metadata=metadata)
        self.emit_workflow(
            LoopEvent(
                event_type="tool_lifecycle",
                turn_index=turn_index,
                data=record.to_dict(),
            )
        )
        return record

    def workflow_context_summary(self, *, recent_limit: int = 20) -> JsonObject:
        recent_edits = self.context_edits[-recent_limit:]
        recent_lifecycle = list(self.tool_lifecycle.values())[-recent_limit:]
        return {
            "abort": self.abort_signal.to_dict(),
            "context_edit_count": len(self.context_edits),
            "context_edits_recent": [edit.to_dict() for edit in recent_edits],
            "context_metadata_keys": sorted(self.metadata.keys()),
            "tool_lifecycle_recent": [record.to_dict() for record in recent_lifecycle],
        }


def project_messages_for_model(
    messages: list[ChatMessage],
    context: ToolUseContext,
    *,
    max_tool_result_chars: int = DEFAULT_TOOL_RESULT_INLINE_CHARS,
) -> list[ChatMessage]:
    """Return a prompt-safe copy with oversized tool results replaced.

    Replacement is keyed by tool_call_id, matching the reference design:
    once a tool result is replaced, later turns reuse the same preview so
    model-visible history remains stable.
    """

    projected: list[ChatMessage] = []
    for message in messages:
        if message.role != "tool" or not message.tool_call_id:
            projected.append(message)
            continue
        replacement = context.tool_result_replacements.get(message.tool_call_id)
        if replacement is not None:
            projected.append(_replace_message_content(message, replacement))
            continue
        content = message.content
        if len(content) <= max_tool_result_chars:
            projected.append(message)
            continue
        artifact_id = context.store_artifact(kind="tool-result", content=content)
        replacement = _large_tool_result_replacement(
            artifact_id=artifact_id,
            original_chars=len(content),
            preview=content[:TOOL_RESULT_PREVIEW_CHARS],
        )
        context.tool_result_replacements[message.tool_call_id] = replacement
        projected.append(_replace_message_content(message, replacement))
    return projected


def tool_message_from_result(
    *,
    tool_call_id: str,
    name: str,
    content: object,
    context: ToolUseContext,
    is_error: bool = False,
    max_inline_chars: int = DEFAULT_TOOL_RESULT_INLINE_CHARS,
    metadata: JsonObject | None = None,
) -> ToolMessage:
    text = stringify_tool_content(content)
    artifact_id: str | None = None
    visible: object = content
    if len(text) > max_inline_chars:
        artifact_id = context.store_artifact(kind="tool-result", content=text)
        visible = json.loads(
            _large_tool_result_replacement(
                artifact_id=artifact_id,
                original_chars=len(text),
                preview=text[:TOOL_RESULT_PREVIEW_CHARS],
            )
        )
    return ToolMessage(
        tool_call_id=tool_call_id,
        name=name,
        content=visible,
        is_error=is_error,
        artifact_id=artifact_id,
        metadata=dict(metadata or {}),
    )


def _replace_message_content(message: ChatMessage, content: str) -> ChatMessage:
    return ChatMessage(
        role=message.role,
        content=content,
        name=message.name,
        tool_call_id=message.tool_call_id,
        tool_calls=message.tool_calls,
        metadata={**message.metadata, "tool_result_replaced": True},
    )


def _large_tool_result_replacement(*, artifact_id: str, original_chars: int, preview: str) -> str:
    return json.dumps(
        {
            "schema": "holo.kernel_v4.large_tool_result_replacement.v1",
            "artifact_id": artifact_id,
            "original_chars": original_chars,
            "preview": preview,
            "instruction": "Use artifact.read with this artifact_id if the preview is insufficient.",
        },
        ensure_ascii=False,
        sort_keys=True,
    )
