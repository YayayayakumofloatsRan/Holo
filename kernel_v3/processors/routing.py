from __future__ import annotations

from dataclasses import replace

from kernel_v3.contracts import JsonObject
from kernel_v3.processors.contracts import ProcessorRoute

DEEPSEEK_V4_FLASH = "deepseek-v4-flash"
DEEPSEEK_V4_PRO = "deepseek-v4-pro"
DEEPSEEK_LEGACY_REASONER = "deepseek-reasoner"
DEEPSEEK_V4_TASK_TYPES = (
    "chat.route",
    "semantic.intake",
    "planner.propose",
    "evaluator.assess",
    "synthesizer.answer",
    "mission.assess",
)


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

    def route_overrides(self) -> dict[str, ProcessorRoute]:
        return {
            task_type: replace(route, parameters=dict(route.parameters))
            for task_type, route in self._routes.items()
        }

    def replace_routes(self, routes: dict[str, ProcessorRoute]) -> None:
        self._routes = {
            task_type: replace(route, parameters=dict(route.parameters))
            for task_type, route in routes.items()
        }

    def set_route(
        self,
        task_type: str,
        *,
        model: str | None = None,
        thinking: str | None = None,
        reasoning_effort: str | None = None,
        temperature: float | None = None,
        latency_target: str | None = None,
        timeout_seconds: int | None = None,
        model_locked: bool = True,
        thinking_locked: bool = True,
        temperature_locked: bool = True,
    ) -> None:
        base = self._routes.get(task_type) or ProcessorRoute(
            task_type=task_type,
            provider=self.default_provider,
            model=self.default_model,
            timeout_seconds=30,
            parameters={},
        )
        parameters = dict(base.parameters)
        if model is not None:
            parameters["model_locked"] = bool(model_locked)
        if thinking is not None:
            parameters["thinking"] = thinking
            parameters["thinking_locked"] = bool(thinking_locked)
            if thinking != "enabled":
                parameters.pop("reasoning_effort", None)
        if reasoning_effort is not None and (thinking is None or thinking == "enabled"):
            parameters["reasoning_effort"] = reasoning_effort
        if temperature is not None:
            parameters["temperature"] = temperature
            parameters["temperature_locked"] = bool(temperature_locked)
        if latency_target is not None:
            parameters["latency_target"] = latency_target
        self._routes[task_type] = replace(
            base,
            model=model or base.model,
            timeout_seconds=timeout_seconds or base.timeout_seconds,
            parameters=parameters,
        )

    def apply_profile(self, profile: str, *, reasoning_effort: str = "high") -> None:
        if profile == "speed":
            target_model = DEEPSEEK_V4_FLASH
            thinking = "disabled"
            latency_target = "fast"
            effort = "low"
        elif profile == "balanced":
            target_model = DEEPSEEK_V4_FLASH
            thinking = "disabled"
            latency_target = "balanced"
            effort = "medium"
        elif profile == "quality":
            target_model = DEEPSEEK_V4_PRO
            thinking = "enabled"
            latency_target = "quality"
            effort = reasoning_effort if reasoning_effort in {"medium", "high", "max"} else "high"
        else:
            raise ValueError(f"unknown processor settings profile: {profile}")
        for task_type in DEEPSEEK_V4_TASK_TYPES:
            self.set_route(
                task_type,
                model=DEEPSEEK_V4_FLASH if task_type == "chat.route" else target_model,
                thinking="disabled" if task_type == "chat.route" else thinking,
                reasoning_effort=effort,
                latency_target=latency_target,
            )


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
            "semantic.intake": (DEEPSEEK_V4_FLASH, "disabled", 1536),
            "planner.propose": (DEEPSEEK_V4_FLASH, "disabled", 2048),
            "evaluator.assess": (DEEPSEEK_V4_FLASH, "disabled", 1024),
            "synthesizer.answer": (DEEPSEEK_V4_FLASH, "disabled", 4096),
            "mission.assess": (DEEPSEEK_V4_FLASH, "disabled", 1536),
        }
    elif profile == "quality":
        specs = {
            "chat.route": (DEEPSEEK_V4_FLASH, "disabled", 384),
            "semantic.intake": (DEEPSEEK_V4_PRO, "enabled", 4096),
            "planner.propose": (DEEPSEEK_V4_PRO, "enabled", 4096),
            "evaluator.assess": (DEEPSEEK_V4_PRO, "enabled", 2048),
            "synthesizer.answer": (DEEPSEEK_V4_PRO, "enabled", 8192),
            "mission.assess": (DEEPSEEK_V4_PRO, "enabled", 4096),
        }
    elif profile == "balanced":
        specs = {
            "chat.route": (DEEPSEEK_V4_FLASH, "disabled", 384),
            "semantic.intake": (DEEPSEEK_V4_FLASH, "disabled", 2048),
            "planner.propose": (DEEPSEEK_V4_FLASH, "disabled", 3072),
            "evaluator.assess": (DEEPSEEK_V4_FLASH, "disabled", 1536),
            "synthesizer.answer": (DEEPSEEK_V4_FLASH, "disabled", 6144),
            "mission.assess": (DEEPSEEK_V4_FLASH, "disabled", 2048),
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
