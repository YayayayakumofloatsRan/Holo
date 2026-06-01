from __future__ import annotations

from dataclasses import dataclass

from kernel_v3.contracts import JsonObject


LATENCY_TARGETS = {"fast", "balanced", "quality", "thorough"}
STRUCTURED_TASK_TYPES = {"chat.route", "semantic.intake", "planner.propose", "evaluator.assess"}


@dataclass(frozen=True, kw_only=True)
class GenerationAssessment:
    prompt_chars: int
    complexity_band: str
    latency_target: str

    def to_dict(self) -> JsonObject:
        return {
            "prompt_chars": self.prompt_chars,
            "complexity_band": self.complexity_band,
            "latency_target": self.latency_target,
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
    )
    explicit_thinking = bool(merged.get("thinking_locked"))
    explicit_temperature = bool(merged.get("temperature_locked"))

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

    merged["timeout_seconds"] = _timeout_for(target=target, current=merged.get("timeout_seconds"))
    merged["generation_policy"] = {
        "mode": "auto",
        "assessment": assessment.to_dict(),
        "thinking_locked": explicit_thinking,
        "temperature_locked": explicit_temperature,
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
        return "enabled"
    if assessment.latency_target == "quality":
        if task_type == "chat.route":
            return "disabled"
        return "enabled"
    if task_type in {"semantic.intake", "evaluator.assess"}:
        return "enabled"
    if task_type in {"planner.propose", "synthesizer.answer"}:
        return "enabled" if assessment.complexity_band in {"large", "huge"} else "disabled"
    return "disabled"


def _reasoning_effort_for(assessment: GenerationAssessment) -> str:
    if assessment.latency_target == "fast":
        return "low"
    if assessment.latency_target == "thorough":
        return "max"
    if assessment.latency_target == "quality":
        return "max" if assessment.complexity_band == "huge" else "high"
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


def _timeout_for(*, target: str, current: object) -> int:
    try:
        parsed = int(current)
    except (TypeError, ValueError):
        parsed = 60
    parsed = max(1, parsed)
    if target == "fast":
        return min(parsed, 30)
    if target == "quality":
        return max(parsed, 90)
    if target == "thorough":
        return max(parsed, 120)
    return parsed
