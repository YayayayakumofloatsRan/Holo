from __future__ import annotations

from kernel_v3.contracts import JsonObject
from kernel_v3.processors.contracts import ProcessorRoute

DEEPSEEK_V4_FLASH = "deepseek-v4-flash"
DEEPSEEK_V4_PRO = "deepseek-v4-pro"
DEEPSEEK_LEGACY_REASONER = "deepseek-reasoner"


class ProcessorRouter:
    def __init__(
        self,
        *,
        default_provider: str = "fake_json",
        default_model: str = "fake-json",
        routes: dict[str, ProcessorRoute] | None = None,
    ) -> None:
        self.default_provider = default_provider
        self.default_model = default_model
        self._routes = dict(routes or {})

    def route(
        self,
        task_type: str,
        *,
        provider: str | None = None,
        model: str | None = None,
        timeout_seconds: int | None = None,
    ) -> ProcessorRoute:
        base = self._routes.get(task_type)
        parameters = dict(base.parameters if base else {})
        if model is not None:
            parameters["model_locked"] = True
        return ProcessorRoute(
            task_type=task_type,
            provider=provider or (base.provider if base else self.default_provider),
            model=model or (base.model if base else self.default_model),
            timeout_seconds=timeout_seconds or (base.timeout_seconds if base else 30),
            parameters=parameters,
        )

    def to_dict(self) -> dict[str, dict[str, object]]:
        return {task_type: route.__dict__ for task_type, route in self._routes.items()}


def deepseek_v4_router(
    *,
    profile: str = "balanced",
    model: str | None = None,
    thinking: str | None = None,
    reasoning_effort: str = "high",
    max_output_tokens: object = "provider",
    temperature: float | None = None,
    generation_mode: str = "manual",
    latency_target: str = "balanced",
) -> ProcessorRouter:
    return ProcessorRouter(
        default_provider="deepseek",
        default_model=DEEPSEEK_V4_FLASH,
        routes=deepseek_v4_routes(
            profile=profile,
            model=model,
            thinking=thinking,
            reasoning_effort=reasoning_effort,
            max_output_tokens=max_output_tokens,
            temperature=temperature,
            generation_mode=generation_mode,
            latency_target=latency_target,
        ),
    )


def deepseek_v4_routes(
    *,
    profile: str = "balanced",
    model: str | None = None,
    thinking: str | None = None,
    reasoning_effort: str = "high",
    max_output_tokens: object = "provider",
    temperature: float | None = None,
    generation_mode: str = "manual",
    latency_target: str = "balanced",
) -> dict[str, ProcessorRoute]:
    effort = _reasoning_effort(reasoning_effort)
    if profile == "fast":
        specs = {
            "chat.route": (DEEPSEEK_V4_FLASH, "disabled", 384),
            "semantic.intake": (DEEPSEEK_V4_FLASH, "disabled", 768),
            "planner.propose": (DEEPSEEK_V4_FLASH, "disabled", 512),
            "evaluator.assess": (DEEPSEEK_V4_FLASH, "disabled", 512),
            "synthesizer.answer": (DEEPSEEK_V4_FLASH, "disabled", 768),
        }
    elif profile == "quality":
        specs = {
            "chat.route": (DEEPSEEK_V4_FLASH, "disabled", 384),
            "semantic.intake": (DEEPSEEK_V4_PRO, "enabled", 1024),
            "planner.propose": (DEEPSEEK_V4_PRO, "enabled", 1024),
            "evaluator.assess": (DEEPSEEK_V4_PRO, "enabled", 768),
            "synthesizer.answer": (DEEPSEEK_V4_PRO, "enabled", 1536),
        }
    elif profile == "balanced":
        specs = {
            "chat.route": (DEEPSEEK_V4_FLASH, "disabled", 384),
            "semantic.intake": (DEEPSEEK_V4_FLASH, "disabled", 1024),
            "planner.propose": (DEEPSEEK_V4_FLASH, "disabled", 1024),
            "evaluator.assess": (DEEPSEEK_V4_FLASH, "disabled", 768),
            "synthesizer.answer": (DEEPSEEK_V4_FLASH, "disabled", 1536),
        }
    else:
        raise ValueError(f"unknown DeepSeek V4 routing profile: {profile}")

    thinking_locked = thinking is not None
    temperature_locked = temperature is not None
    model_locked = model is not None
    return {
        task_type: _deepseek_route(
            task_type,
            model or route_model,
            thinking=thinking or default_thinking,
            reasoning_effort=effort,
            max_tokens=_route_max_tokens(default_max_tokens, max_output_tokens),
            temperature=temperature,
            generation_mode=generation_mode,
            latency_target=latency_target,
            thinking_locked=thinking_locked,
            temperature_locked=temperature_locked,
            model_locked=model_locked,
        )
        for task_type, (route_model, default_thinking, default_max_tokens) in specs.items()
    }


def _deepseek_route(
    task_type: str,
    model: str,
    *,
    thinking: str,
    max_tokens: int | None,
    reasoning_effort: str | None = None,
    temperature: float | None = None,
    generation_mode: str = "manual",
    latency_target: str = "balanced",
    thinking_locked: bool = False,
    temperature_locked: bool = False,
    model_locked: bool = False,
) -> ProcessorRoute:
    parameters: JsonObject = {
        "thinking": thinking,
        "generation_mode": generation_mode if generation_mode in {"auto", "manual"} else "manual",
        "latency_target": latency_target if latency_target in {"fast", "balanced", "quality", "thorough"} else "balanced",
        "thinking_locked": thinking_locked,
        "temperature_locked": temperature_locked,
        "model_locked": model_locked,
    }
    if max_tokens is not None:
        parameters["max_tokens"] = max_tokens
    if thinking == "enabled" and reasoning_effort:
        parameters["reasoning_effort"] = reasoning_effort
    if temperature is not None:
        parameters["temperature"] = temperature
    return ProcessorRoute(
        task_type=task_type,
        provider="deepseek",
        model=model,
        timeout_seconds=90 if thinking == "enabled" else 60,
        parameters=parameters,
    )


def _reasoning_effort(value: str) -> str:
    if value in {"low", "medium", "high", "max"}:
        return value
    return "high"


def _route_max_tokens(default: int, override: object) -> int | None:
    if override is None or override == "auto":
        return default
    if isinstance(override, str) and override.lower() in {"none", "provider", "provider-default", "off"}:
        return None
    try:
        parsed = int(override)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else None
