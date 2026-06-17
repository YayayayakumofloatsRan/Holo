from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from kernel_v3.contracts import CandidateAction, JsonObject, ToolManifest


TOOL_RUNTIME_SCHEMA = "holo.kernel_v3.tool_runtime_spec.v1"
DEFAULT_MAX_RESULT_SIZE_CHARS = 50_000


@dataclass(frozen=True, kw_only=True)
class ToolRuntimeSpec:
    concurrency_safe: bool
    read_only: bool
    destructive: bool
    open_world: bool
    requires_user_interaction: bool
    interrupt_behavior: str
    max_result_size_chars: int | None
    result_persistence_policy: str
    should_defer: bool
    always_load: bool
    progress_supported: bool
    timeout_seconds: int | None
    idempotent: bool

    def to_dict(self) -> JsonObject:
        return {
            "schema": TOOL_RUNTIME_SCHEMA,
            "concurrency_safe": self.concurrency_safe,
            "read_only": self.read_only,
            "destructive": self.destructive,
            "open_world": self.open_world,
            "requires_user_interaction": self.requires_user_interaction,
            "interrupt_behavior": self.interrupt_behavior,
            "max_result_size_chars": self.max_result_size_chars,
            "result_persistence_policy": self.result_persistence_policy,
            "should_defer": self.should_defer,
            "always_load": self.always_load,
            "progress_supported": self.progress_supported,
            "timeout_seconds": self.timeout_seconds,
            "idempotent": self.idempotent,
        }


def tool_runtime_spec_for_action(
    action: CandidateAction,
    manifest: ToolManifest | None,
) -> ToolRuntimeSpec:
    side_effect = str(getattr(manifest, "side_effect_class", action.side_effect_class) or action.side_effect_class)
    runtime = dict(getattr(manifest, "runtime", {}) or {}) if manifest is not None else {}
    schema = getattr(manifest, "input_schema", {}) if manifest is not None else {}
    schema_runtime = schema.get("_runtime") if isinstance(schema, dict) else {}
    if isinstance(schema_runtime, dict):
        runtime = {**schema_runtime, **runtime}

    destructive = _bool(runtime.get("destructive"), default=side_effect == "destructive")
    read_only = _bool(runtime.get("read_only"), default=side_effect in {"none", "read", "network"} and not destructive)
    open_world = _bool(runtime.get("open_world"), default=side_effect in {"network", "shell"})
    concurrency_default = False
    legacy_concurrency = schema.get("concurrency_safe") if isinstance(schema, dict) else None
    if legacy_concurrency is True and side_effect in {"none", "read", "network"} and not destructive:
        concurrency_default = True
    concurrency_safe = _bool(runtime.get("concurrency_safe"), default=concurrency_default)
    if destructive or side_effect in {"write", "shell", "destructive"}:
        concurrency_safe = False

    interrupt_behavior = str(runtime.get("interrupt_behavior") or "block").strip().lower()
    if interrupt_behavior not in {"cancel", "block"}:
        interrupt_behavior = "block"

    max_result = _positive_int_or_none(runtime.get("max_result_size_chars"))
    if max_result is None and runtime.get("max_result_size_chars") != "infinity":
        max_result = DEFAULT_MAX_RESULT_SIZE_CHARS
    if str(runtime.get("max_result_size_chars")).lower() in {"infinity", "inf", "none"}:
        max_result = None

    policy = str(runtime.get("result_persistence_policy") or "auto").strip().lower()
    if policy not in {"auto", "never", "always", "artifact"}:
        policy = "auto"

    return ToolRuntimeSpec(
        concurrency_safe=concurrency_safe,
        read_only=read_only,
        destructive=destructive,
        open_world=open_world,
        requires_user_interaction=_bool(runtime.get("requires_user_interaction"), default=False),
        interrupt_behavior=interrupt_behavior,
        max_result_size_chars=max_result,
        result_persistence_policy=policy,
        should_defer=_bool(runtime.get("should_defer"), default=False),
        always_load=_bool(runtime.get("always_load"), default=False),
        progress_supported=_bool(runtime.get("progress_supported"), default=False),
        timeout_seconds=_positive_int_or_none(runtime.get("timeout_seconds")),
        idempotent=_bool(runtime.get("idempotent"), default=read_only and not open_world),
    )


def tool_runtime_spec_for_manifest(manifest: ToolManifest) -> ToolRuntimeSpec:
    return tool_runtime_spec_for_action(
        CandidateAction(
            action_id=f"manifest-{manifest.name}-runtime",
            kind="tool",
            name=manifest.name,
            description=manifest.description,
            score=1.0,
            payload={},
            reasons=["manifest_runtime_projection"],
            side_effect_class=manifest.side_effect_class,
        ),
        manifest,
    )


def _bool(value: object, *, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off"}:
            return False
    return default


def _positive_int_or_none(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None
