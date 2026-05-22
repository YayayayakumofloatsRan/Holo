from __future__ import annotations

import json
from typing import Any

from .common import compact_text

STAGE122_SCHEMA = "holo.stage122.internal_external_channel_boundary.v1"

STAGE122_CONTRACT_MARKER = "Stage122 Channel Boundary"

_STABLE_PROVIDER_CONTRACT_LINES = (
    f"{STAGE122_CONTRACT_MARKER}:",
    "- internal_intent is local planning metadata about what Holo is trying to do next.",
    "- internal_processing is a local-only summary of phases, tool needs, and state transitions.",
    "- Do not reveal raw hidden reasoning or internal_processing traces.",
    "- external_speech_only: write only the user-facing answer that should be visible outside Holo.",
)


def _tool_names(tool_requests: Any) -> list[str]:
    names: list[str] = []
    for raw in list(tool_requests or []):
        item = dict(raw) if isinstance(raw, dict) else {}
        name = str(item.get("name", "") or "").strip()
        if name and name not in names:
            names.append(name)
    return names


def _policy_path(stage121_packet_policy: Any, *path: str, default: Any = None) -> Any:
    current = stage121_packet_policy if isinstance(stage121_packet_policy, dict) else {}
    for key in path:
        if not isinstance(current, dict) or key not in current:
            return default
        current = current[key]
    return current


def _safe_phases(stage121_packet_policy: Any) -> list[str]:
    phases = _policy_path(stage121_packet_policy, "continuity", "phases", default=[])
    if not isinstance(phases, list):
        return ["context_seed", "expression_commit"]
    normalized = [str(item).strip() for item in phases if str(item).strip()]
    return normalized or ["context_seed", "expression_commit"]


def _intent_mode(
    *,
    stream_mode: str,
    selected_action_type: str,
    tool_names: list[str],
    uncertainty_level: float,
) -> str:
    if stream_mode == "continuous_thought" or float(uncertainty_level or 0.0) >= 0.72:
        return "continue_internal_deliberation"
    if selected_action_type in {"external_lookup", "history_refresh", "visual_recall", "operator_self_fix"}:
        return "ground_state_before_speaking"
    if tool_names:
        return "tool_grounded_deliberation"
    return "compose_external_reply"


def provider_contract_text() -> str:
    return "\n".join(_STABLE_PROVIDER_CONTRACT_LINES)


def build_stage122_channel_frame(
    *,
    user_text: str,
    selected_action_type: str,
    stage121_packet_policy: Any,
    tool_requests: Any,
    uncertainty_level: float = 0.0,
) -> dict[str, Any]:
    tool_names = _tool_names(tool_requests)
    stream_mode = str(_policy_path(stage121_packet_policy, "continuity", "stream_mode", default="compact_reply_packet") or "compact_reply_packet")
    phases = _safe_phases(stage121_packet_policy)
    intent_mode = _intent_mode(
        stream_mode=stream_mode,
        selected_action_type=str(selected_action_type or ""),
        tool_names=tool_names,
        uncertainty_level=float(uncertainty_level or 0.0),
    )
    packet_digest = str(_policy_path(stage121_packet_policy, "cache", "stable_prefix_digest", default="") or "")

    return {
        "schema": STAGE122_SCHEMA,
        "stage": 122,
        "user_input": {
            "role": "external_user",
            "summary": compact_text(user_text, 180),
            "visible_to_user": True,
        },
        "internal_intent": {
            "role": "local_subject_controller",
            "mode": intent_mode,
            "selected_action_type": str(selected_action_type or ""),
            "stream_mode": stream_mode,
            "visible_to_user": False,
        },
        "internal_processing": {
            "role": "local_runtime_summary",
            "phases": phases,
            "tool_names": tool_names,
            "uncertainty_level": round(float(uncertainty_level or 0.0), 4),
            "stage121_stable_prefix_digest": packet_digest,
            "summary_only": True,
            "visible_to_user": False,
            "raw_hidden_reasoning_disallowed": True,
        },
        "external_speech": {
            "role": "user_visible_expression",
            "commit_phase": "expression_commit",
            "external_speech_only": True,
            "visible_to_user": True,
            "may_include_internal_processing": False,
            "may_include_tool_observations": "only when summarized for the user",
        },
        "provider_contract_text": provider_contract_text(),
    }


def append_stage122_channel_contract(prompt: str, channel_frame: dict[str, Any] | None = None) -> str:
    text = str(prompt or "")
    if STAGE122_CONTRACT_MARKER in text:
        return text
    contract = provider_contract_text()
    return f"{text.rstrip()}\n\n{contract}".strip()


def build_stage122_channel_report(**kwargs: Any) -> dict[str, Any]:
    frame = build_stage122_channel_frame(**kwargs)
    return json.loads(json.dumps(frame, ensure_ascii=False, sort_keys=True))
