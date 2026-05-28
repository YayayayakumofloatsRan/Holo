from __future__ import annotations

import re
from typing import Any

PROMPT_POLICY_SCHEMA = "holo.stage160r.prompt_policy.v1"

AGENT_KERNEL_CHANNELS = {"holo_cli", "engineering", "research", "project"}

_BANNED_PERSONA_FRAGMENTS = (
    "\u5fae\u4fe1",
    "\u719f\u4eba",
    "\u8d34\u7740\u8bf4\u8bdd",
    "\u6253\u8da3",
    "\u72e1\u9ee0",
    "\u998b",
    "the subject",
    "\u966a\u4f60",
    "\u957f\u8f88",
    "\u8bf4\u6559",
    "persona blend",
    "relationship stance",
    "affect state",
    "homeostasis state",
    "consciousness lines",
)

_PERSONA_SECTION_TITLES = {
    "Persona Blend:",
    "Relationship Stance:",
    "Affect State:",
    "Homeostasis State:",
    "Drive State:",
    "Value State:",
    "Conflict State:",
    "Resistance Posture:",
    "Consciousness Lines:",
    "Stream Influence:",
    "Outcome Memory:",
}


def _is_agent_kernel_channel(channel: str) -> bool:
    current = str(channel or "").strip().lower()
    return current in AGENT_KERNEL_CHANNELS or any(current.startswith(prefix + "_") for prefix in AGENT_KERNEL_CHANNELS)


def prompt_policy_for_channel(channel: str) -> dict[str, Any]:
    depersonalized = _is_agent_kernel_channel(channel)
    return {
        "schema": PROMPT_POLICY_SCHEMA,
        "channel": str(channel or ""),
        "mode": "depersonalized_agent_kernel" if depersonalized else "channel_default",
        "depersonalized": depersonalized,
        "allowed_visible_outputs": [
            "engineering_assistant_answer",
            "concise_agent_reasoning_summary",
            "evidence_status",
            "action_trace",
            "failure_report",
            "grounded_final",
        ]
        if depersonalized
        else [],
        "forbidden_visible_outputs": [
            "companion_persona",
            "roleplay",
            "wechat_tone",
            "playful_teasing",
            "playful_metaphor_failure_report",
            "inner_emotional_performance",
            "fixed_persona_opener",
        ]
        if depersonalized
        else [],
    }


def _contains_banned_fragment(line: str) -> bool:
    lowered = str(line or "").lower()
    return any(fragment and fragment.lower() in lowered for fragment in _BANNED_PERSONA_FRAGMENTS)


def strip_persona_prompt_text(prompt: str, *, channel: str) -> str:
    if not _is_agent_kernel_channel(channel):
        return str(prompt or "")
    lines = str(prompt or "").splitlines()
    cleaned: list[str] = []
    skip_section = False
    for line in lines:
        stripped = line.strip()
        if stripped in _PERSONA_SECTION_TITLES:
            skip_section = True
            continue
        if skip_section:
            if not stripped:
                skip_section = False
            continue
        if _contains_banned_fragment(line):
            continue
        cleaned.append(line)
    text = "\n".join(cleaned)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    policy = (
        "Agent Kernel Prompt Policy:\n"
        "- identity: Holo is a depersonalized engineering assistant and research operator\n"
        "- operate as an engineering agent; do not switch into social chat or character style\n"
        "- use observe -> decide -> act_or_skip -> observe_result -> evaluate_stop -> repeat_or_final\n"
        "- visible output is limited to evidence status, action trace, failure report, and grounded final\n"
        "- report tool/web failures plainly as attempted actions with status and error evidence\n"
        "- do not expose hidden reasoning\n"
    )
    return policy + ("\n" + text if text else "")


def assert_no_persona_prompt_leak(prompt: str, *, channel: str) -> tuple[bool, list[str]]:
    if not _is_agent_kernel_channel(channel):
        return True, []
    lowered = str(prompt or "").lower()
    leaks = [fragment for fragment in _BANNED_PERSONA_FRAGMENTS if fragment and fragment.lower() in lowered]
    return not leaks, sorted(set(leaks))
