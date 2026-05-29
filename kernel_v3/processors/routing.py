from __future__ import annotations

from kernel_v3.processors.contracts import ProcessorRoute


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
        )

    def to_dict(self) -> dict[str, dict[str, object]]:
        return {task_type: route.__dict__ for task_type, route in self._routes.items()}
