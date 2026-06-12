from __future__ import annotations

import json
from dataclasses import dataclass

from kernel_v3.contracts import JsonObject


LATENCY_TARGETS = {"fast", "balanced", "quality", "thorough"}
STRUCTURED_TASK_TYPES = {
    "chat.route",
    "semantic.intake",
    "planner.propose",
    "task.compile",
    "retrieval.workbench",
    "evaluator.assess",
    "mission.assess",
    "workmethod.frame",
    "workmethod.gap",
}
DEEPSEEK_FLASH_MODEL = "deepseek-v4-flash"
DEEPSEEK_PRO_MODEL = "deepseek-v4-pro"
DEEPSEEK_MODELS = {DEEPSEEK_FLASH_MODEL, DEEPSEEK_PRO_MODEL, "deepseek-reasoner"}


@dataclass(frozen=True, kw_only=True)
class GenerationAssessment:
    prompt_chars: int
    complexity_band: str
    latency_target: str
    task_difficulty: str

    def to_dict(self) -> JsonObject:
        return {
            "prompt_chars": self.prompt_chars,
            "complexity_band": self.complexity_band,
            "latency_target": self.latency_target,
            "task_difficulty": self.task_difficulty,
        }


def adapt_generation_parameters(
    *,
    task_type: str,
    prompt: str,
    parameters: JsonObject,
) -> JsonObject:
    """Apply host-owned generation policy without changing explicit user controls."""

    merged = dict(parameters)
    if str(merged.get("generation_mode", "manual")) != "auto":
        return merged

    target = _latency_target(merged.get("latency_target"))
    assessment = GenerationAssessment(
        prompt_chars=len(prompt),
        complexity_band=_complexity_band(len(prompt)),
        latency_target=target,
        task_difficulty=_task_difficulty(prompt),
    )
    explicit_thinking = bool(merged.get("thinking_locked"))
    explicit_temperature = bool(merged.get("temperature_locked"))
    explicit_model = bool(merged.get("model_locked"))
    model_before = str(merged.get("model") or "")

    if not explicit_model:
        merged["model"] = _model_for(
            task_type=task_type,
            assessment=assessment,
            provider=str(merged.get("provider") or ""),
            current_model=model_before,
        )

    if not explicit_thinking:
        merged["thinking"] = _thinking_for(task_type=task_type, assessment=assessment)

    thinking_enabled = merged.get("thinking") == "enabled"
    if thinking_enabled:
        if not explicit_thinking or "reasoning_effort" not in merged:
            merged["reasoning_effort"] = _reasoning_effort_for(assessment)
    else:
        merged.pop("reasoning_effort", None)

    if not explicit_temperature:
        merged["temperature"] = _temperature_for(task_type=task_type, assessment=assessment)

    merged["timeout_seconds"] = _timeout_for(
        target=target,
        current=merged.get("timeout_seconds"),
        thinking_enabled=thinking_enabled,
    )
    merged["generation_policy"] = {
        "mode": "auto",
        "assessment": assessment.to_dict(),
        "thinking_locked": explicit_thinking,
        "temperature_locked": explicit_temperature,
        "model_locked": explicit_model,
        "model_before": model_before,
        "model_after": str(merged.get("model") or ""),
    }
    return merged


def _latency_target(value: object) -> str:
    if isinstance(value, str) and value in LATENCY_TARGETS:
        return value
    return "balanced"


def _complexity_band(prompt_chars: int) -> str:
    if prompt_chars >= 80_000:
        return "huge"
    if prompt_chars >= 20_000:
        return "large"
    if prompt_chars >= 4_000:
        return "medium"
    return "small"


def _thinking_for(*, task_type: str, assessment: GenerationAssessment) -> str:
    if assessment.latency_target == "fast":
        return "disabled"
    if assessment.latency_target == "thorough":
        if task_type == "chat.route":
            return "disabled"
        return "enabled"
    if assessment.latency_target == "quality":
        if task_type == "chat.route":
            return "disabled"
        return "enabled"
    if assessment.latency_target == "balanced":
        if task_type == "chat.route":
            return "disabled"
        if assessment.task_difficulty in {"replan", "deep_research"} and task_type in {
            "planner.propose",
            "task.compile",
            "retrieval.workbench",
            "evaluator.assess",
            "mission.assess",
            "workmethod.frame",
            "workmethod.gap",
            "synthesizer.answer",
        }:
            return "enabled"
    return "disabled"


def _model_for(*, task_type: str, assessment: GenerationAssessment, provider: str, current_model: str) -> str:
    if provider != "deepseek" and current_model not in DEEPSEEK_MODELS:
        return current_model
    if task_type == "chat.route" or assessment.latency_target == "fast":
        return DEEPSEEK_FLASH_MODEL
    if assessment.latency_target in {"quality", "thorough"}:
        return DEEPSEEK_PRO_MODEL
    if assessment.latency_target == "balanced" and assessment.task_difficulty in {"replan", "deep_research"}:
        if task_type in {
            "planner.propose",
            "task.compile",
            "retrieval.workbench",
            "mission.assess",
            "workmethod.frame",
            "workmethod.gap",
            "synthesizer.answer",
        }:
            return DEEPSEEK_PRO_MODEL
    return DEEPSEEK_FLASH_MODEL


def _reasoning_effort_for(assessment: GenerationAssessment) -> str:
    if assessment.latency_target == "fast":
        return "low"
    if assessment.latency_target == "thorough":
        return "max"
    if assessment.latency_target == "quality":
        return "max" if assessment.complexity_band == "huge" else "high"
    if assessment.task_difficulty == "deep_research":
        return "high"
    if assessment.task_difficulty == "replan":
        return "medium"
    if assessment.complexity_band in {"large", "huge"}:
        return "high"
    if assessment.complexity_band == "medium":
        return "medium"
    return "low"


def _temperature_for(*, task_type: str, assessment: GenerationAssessment) -> float:
    if task_type in STRUCTURED_TASK_TYPES:
        return 0.0
    if task_type == "synthesizer.answer":
        return 0.2 if assessment.latency_target in {"quality", "thorough"} else 0.1
    return 0.0


def _timeout_for(*, target: str, current: object, thinking_enabled: bool) -> int:
    try:
        parsed = int(current)
    except (TypeError, ValueError):
        parsed = 60
    parsed = max(1, parsed)
    if target == "fast":
        return min(parsed, 30)
    if target == "balanced":
        if thinking_enabled:
            return max(parsed, 90)
        return min(max(parsed, 30), 60)
    if target == "quality":
        return max(parsed, 120)
    if target == "thorough":
        return max(parsed, 180)
    return parsed


def _task_difficulty(prompt: str) -> str:
    """Classify prompt difficulty from host state, not user keyword tables."""

    payload = _json_payload(prompt)
    if _has_replan_signal(payload):
        return "replan"
    answer_profile = _find_object(payload, "answer_profile")
    if answer_profile:
        format_name = str(answer_profile.get("format") or "")
        detail_level = str(answer_profile.get("detail_level") or "")
        metadata = answer_profile.get("metadata")
        metadata = metadata if isinstance(metadata, dict) else {}
        quality_gate = str(answer_profile.get("quality_gate") or metadata.get("quality_gate") or "")
        if format_name == "deep_report" or detail_level == "deep":
            return "deep_research"
        if format_name in {"detailed_report", "memo"} and quality_gate == "strict":
            return "deep_research"
        if format_name in {"detailed_report", "memo"}:
            return "research"
    if _find_object(payload, "research_mission") or _find_object(payload, "mission_context"):
        return "research"
    return "routine"


def _json_payload(prompt: str) -> object:
    text = str(prompt or "").strip()
    if not text:
        return {}
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {}


def _has_replan_signal(value: object) -> bool:
    if isinstance(value, dict):
        status = value.get("status")
        if status in {"needs_replan", "continue_or_fail_under_host_guards"}:
            return True
        if value.get("needs_replan") is True:
            return True
        if value.get("primary_failure_mode") not in {None, "", "none"}:
            return True
        return any(_has_replan_signal(item) for item in value.values())
    if isinstance(value, list):
        return any(_has_replan_signal(item) for item in value)
    return False


def _find_object(value: object, key: str) -> JsonObject:
    if isinstance(value, dict):
        found = value.get(key)
        if isinstance(found, dict):
            return dict(found)
        for item in value.values():
            nested = _find_object(item, key)
            if nested:
                return nested
    elif isinstance(value, list):
        for item in value:
            nested = _find_object(item, key)
            if nested:
                return nested
    return {}
