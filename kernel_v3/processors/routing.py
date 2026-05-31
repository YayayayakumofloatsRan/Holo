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
        return ProcessorRoute(
            task_type=task_type,
            provider=provider or (base.provider if base else self.default_provider),
            model=model or (base.model if base else self.default_model),
            timeout_seconds=timeout_seconds or (base.timeout_seconds if base else 30),
            parameters=dict(base.parameters if base else {}),
        )

    def to_dict(self) -> dict[str, dict[str, object]]:
        return {task_type: route.__dict__ for task_type, route in self._routes.items()}


def deepseek_v4_router(
    *,
    profile: str = "balanced",
    thinking: str | None = None,
    reasoning_effort: str = "high",
) -> ProcessorRouter:
    return ProcessorRouter(
        default_provider="deepseek",
        default_model=DEEPSEEK_V4_FLASH,
        routes=deepseek_v4_routes(profile=profile, thinking=thinking, reasoning_effort=reasoning_effort),
    )


def deepseek_v4_routes(
    *,
    profile: str = "balanced",
    thinking: str | None = None,
    reasoning_effort: str = "high",
) -> dict[str, ProcessorRoute]:
    effort = _reasoning_effort(reasoning_effort)
    if profile == "fast":
        return {
            "chat.route": _deepseek_route(
                "chat.route",
                DEEPSEEK_V4_FLASH,
                thinking=thinking or "disabled",
                reasoning_effort=effort,
                max_tokens=384,
            ),
            "semantic.intake": _deepseek_route(
                "semantic.intake",
                DEEPSEEK_V4_FLASH,
                thinking=thinking or "disabled",
                reasoning_effort=effort,
                max_tokens=768,
            ),
            "planner.propose": _deepseek_route(
                "planner.propose",
                DEEPSEEK_V4_FLASH,
                thinking=thinking or "disabled",
                reasoning_effort=effort,
                max_tokens=512,
            ),
            "evaluator.assess": _deepseek_route(
                "evaluator.assess",
                DEEPSEEK_V4_FLASH,
                thinking=thinking or "disabled",
                reasoning_effort=effort,
                max_tokens=512,
            ),
            "synthesizer.answer": _deepseek_route(
                "synthesizer.answer",
                DEEPSEEK_V4_FLASH,
                thinking=thinking or "disabled",
                reasoning_effort=effort,
                max_tokens=768,
            ),
        }
    if profile == "quality":
        return {
            "chat.route": _deepseek_route(
                "chat.route",
                DEEPSEEK_V4_FLASH,
                thinking=thinking or "disabled",
                reasoning_effort=effort,
                max_tokens=384,
            ),
            "semantic.intake": _deepseek_route(
                "semantic.intake",
                DEEPSEEK_V4_PRO,
                thinking=thinking or "enabled",
                reasoning_effort=effort,
                max_tokens=1024,
            ),
            "planner.propose": _deepseek_route(
                "planner.propose",
                DEEPSEEK_V4_PRO,
                thinking=thinking or "disabled",
                reasoning_effort=effort,
                max_tokens=512,
            ),
            "evaluator.assess": _deepseek_route(
                "evaluator.assess",
                DEEPSEEK_V4_PRO,
                thinking=thinking or "enabled",
                reasoning_effort=effort,
                max_tokens=768,
            ),
            "synthesizer.answer": _deepseek_route(
                "synthesizer.answer",
                DEEPSEEK_V4_PRO,
                thinking=thinking or "disabled",
                reasoning_effort=effort,
                max_tokens=1024,
            ),
        }
    if profile != "balanced":
        raise ValueError(f"unknown DeepSeek V4 routing profile: {profile}")
    return {
        "chat.route": _deepseek_route(
            "chat.route",
            DEEPSEEK_V4_FLASH,
            thinking=thinking or "disabled",
            reasoning_effort=effort,
            max_tokens=384,
        ),
        "semantic.intake": _deepseek_route(
            "semantic.intake",
            DEEPSEEK_V4_PRO,
            thinking=thinking or "enabled",
            reasoning_effort=effort,
            max_tokens=1024,
        ),
        "planner.propose": _deepseek_route(
            "planner.propose",
            DEEPSEEK_V4_FLASH,
            thinking=thinking or "disabled",
            reasoning_effort=effort,
            max_tokens=512,
        ),
        "evaluator.assess": _deepseek_route(
            "evaluator.assess",
            DEEPSEEK_V4_PRO,
            thinking=thinking or "enabled",
            reasoning_effort=effort,
            max_tokens=768,
        ),
        "synthesizer.answer": _deepseek_route(
            "synthesizer.answer",
            DEEPSEEK_V4_PRO,
            thinking=thinking or "disabled",
            reasoning_effort=effort,
            max_tokens=1024,
        ),
    }


def _deepseek_route(
    task_type: str,
    model: str,
    *,
    thinking: str,
    max_tokens: int,
    reasoning_effort: str | None = None,
) -> ProcessorRoute:
    parameters: JsonObject = {"thinking": thinking, "max_tokens": max_tokens}
    if thinking == "enabled" and reasoning_effort:
        parameters["reasoning_effort"] = reasoning_effort
    return ProcessorRoute(
        task_type=task_type,
        provider="deepseek",
        model=model,
        timeout_seconds=60,
        parameters=parameters,
    )


def _reasoning_effort(value: str) -> str:
    if value == "max":
        return "max"
    return "high"
