from __future__ import annotations

import json
from typing import Any

STAGE123_SCHEMA = "holo.stage123.internal_tool_flow.v1"

STAGE123_CONTRACT_MARKER = "Stage123 Internal Tool Flow"

_STABLE_PROVIDER_CONTRACT_LINES = (
    f"{STAGE123_CONTRACT_MARKER}:",
    "- If internal_intent needs memory, evidence, lookup, workspace state, or verification, use exposed tool_calls before external_speech.",
    "- Provider may propose tool_calls only; Holo Stage113 executes tools locally inside the WSL brain.",
    "- Tool observations re-enter the next provider packet before external_speech is committed.",
    "- Never fabricate tool results; if a tool is unavailable or rejected, explain the limitation in external_speech.",
)


def _tool_names(tool_requests: Any) -> list[str]:
    names: list[str] = []
    for raw in list(tool_requests or []):
        item = dict(raw) if isinstance(raw, dict) else {}
        name = str(item.get("name", "") or "").strip()
        if name and name not in names:
            names.append(name)
    return names


def _channel_path(stage122_channel_frame: Any, *path: str, default: Any = None) -> Any:
    current = stage122_channel_frame if isinstance(stage122_channel_frame, dict) else {}
    for key in path:
        if not isinstance(current, dict) or key not in current:
            return default
        current = current[key]
    return current


def _requires_tool_before_speech(intent_mode: str, tool_names: list[str]) -> bool:
    if not tool_names:
        return False
    return intent_mode in {
        "continue_internal_deliberation",
        "tool_grounded_deliberation",
        "ground_state_before_speaking",
    }


def internal_tool_contract_text() -> str:
    return "\n".join(_STABLE_PROVIDER_CONTRACT_LINES)


def build_stage123_internal_tool_flow(
    *,
    stage122_channel_frame: Any,
    tool_requests: Any,
) -> dict[str, Any]:
    tool_names = _tool_names(tool_requests)
    intent_mode = str(_channel_path(stage122_channel_frame, "internal_intent", "mode", default="compose_external_reply") or "compose_external_reply")
    stream_mode = str(_channel_path(stage122_channel_frame, "internal_intent", "stream_mode", default="compact_reply_packet") or "compact_reply_packet")
    enabled = bool(tool_names)
    call_before_speech = _requires_tool_before_speech(intent_mode, tool_names)

    required_phases = ["internal_intent"]
    if enabled:
        required_phases.extend(["provider_tool_call", "stage113_local_execution", "tool_observation_reentry"])
    required_phases.append("external_speech")

    return {
        "schema": STAGE123_SCHEMA,
        "stage": 123,
        "internal_tool_calls": {
            "enabled": enabled,
            "call_before_external_speech": call_before_speech,
            "intent_mode": intent_mode,
            "stream_mode": stream_mode,
            "proposed_tool_names": tool_names,
            "visible_to_user": False,
        },
        "tool_authority": {
            "provider_may_propose_tools": enabled,
            "provider_may_execute_tools": False,
            "executor": "holo_wsl_brain_stage113",
            "permission_boundary": "stage113_allowlist_and_grants",
            "windows_transport_may_execute_tools": False,
        },
        "loop_contract": {
            "required_phases": required_phases,
            "tool_observations_reenter_provider": enabled,
            "observation_format": "bounded_tool_observation",
            "fallback_when_no_tool_needed": "commit_external_speech",
        },
        "external_expression_gate": {
            "requires_observation_or_no_tool_needed": True,
            "external_speech_after_tool_loop": enabled,
            "may_summarize_tool_observations": True,
            "must_not_fabricate_tool_results": True,
        },
        "provider_contract_text": internal_tool_contract_text(),
    }


def append_stage123_internal_tool_contract(prompt: str, internal_tool_flow: dict[str, Any] | None = None) -> str:
    text = str(prompt or "")
    if STAGE123_CONTRACT_MARKER in text:
        return text
    contract = internal_tool_contract_text()
    return f"{text.rstrip()}\n\n{contract}".strip()


def build_stage123_internal_tool_report(**kwargs: Any) -> dict[str, Any]:
    flow = build_stage123_internal_tool_flow(**kwargs)
    return json.loads(json.dumps(flow, ensure_ascii=False, sort_keys=True))
