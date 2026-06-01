from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable

from kernel_v3.contracts import JsonObject, ProcessorRequest, ProcessorResult
from kernel_v3.journal import JournalStore
from kernel_v3.journal_redaction import redact_journal_data
from kernel_v3.processors.contracts import JsonSchema, ProcessorOutcome, ProcessorProvider
from kernel_v3.processors.json_repair import parse_json_object
from kernel_v3.processors.routing import ProcessorRouter
from kernel_v3.processors.usage import coerce_usage


class ProcessorFabric:
    def __init__(
        self,
        *,
        providers: dict[str, ProcessorProvider],
        router: ProcessorRouter | None = None,
        journal: JournalStore | None = None,
        clock_ms: Callable[[], int] | None = None,
        max_repair_attempts: int = 1,
    ) -> None:
        self.providers = dict(providers)
        self.router = router or ProcessorRouter()
        self.journal = journal
        self.clock_ms = clock_ms or (lambda: time.monotonic_ns() // 1_000_000)
        self.max_repair_attempts = max(0, max_repair_attempts)
        self._counter = 0

    def run_json(
        self,
        *,
        task_type: str,
        run_id: str,
        context_id: str,
        prompt: str,
        schema: JsonSchema,
        task_id: str | None = None,
        step_id: str | None = None,
        provider: str | None = None,
        model: str | None = None,
        timeout_seconds: int | None = None,
        parameters: JsonObject | None = None,
    ) -> ProcessorOutcome:
        route = self.router.route(task_type, provider=provider, model=model, timeout_seconds=timeout_seconds)
        selected = self.providers.get(route.provider)
        if selected is None:
            request = self._request(
                task_type=task_type,
                run_id=run_id,
                context_id=context_id,
                prompt=prompt,
                route_provider=route.provider,
                route_model=route.model,
                timeout_seconds=route.timeout_seconds,
                route_parameters=route.parameters,
                parameters=parameters,
            )
            self._journal_request(task_id=task_id, run_id=run_id, step_id=step_id, request=request)
            result = ProcessorResult(
                result_id=f"result-{request.request_id}",
                request_id=request.request_id,
                status="failed",
                output={"provider": route.provider, "model": route.model},
                usage={},
                error="provider_not_registered",
            )
            self._journal_result(
                task_id=task_id,
                run_id=run_id,
                step_id=step_id,
                request=request,
                result=result,
                provider=route.provider,
                model=route.model,
                task_type=task_type,
                duration_ms=0,
            )
            return ProcessorOutcome(
                request=request,
                result=result,
                parsed=None,
                provider=route.provider,
                model=route.model,
                task_type=task_type,
                duration_ms=0,
            )

        provider_model = route.model
        request = self._request(
            task_type=task_type,
            run_id=run_id,
            context_id=context_id,
            prompt=prompt,
            route_provider=route.provider,
            route_model=provider_model,
            timeout_seconds=route.timeout_seconds,
            route_parameters=route.parameters,
            parameters=parameters,
        )
        self._journal_request(task_id=task_id, run_id=run_id, step_id=step_id, request=request)
        started = self.clock_ms()
        provider_result: ProcessorResult | None = None
        try:
            provider_result = selected.run(request)
        except Exception as exc:  # concrete providers normalize availability, but host catches all provider faults.
            duration_ms = max(0, self.clock_ms() - started)
            result = ProcessorResult(
                result_id=f"result-{request.request_id}",
                request_id=request.request_id,
                status="failed",
                output={
                    "provider": route.provider,
                    "model": provider_model,
                    "error_type": type(exc).__name__,
                    "error_message_preview": _preview(str(exc) or type(exc).__name__, 240),
                },
                usage={},
                error=type(exc).__name__,
            )
            self._journal_result(
                task_id=task_id,
                run_id=run_id,
                step_id=step_id,
                request=request,
                result=result,
                provider=route.provider,
                model=provider_model,
                task_type=task_type,
                duration_ms=duration_ms,
            )
            return ProcessorOutcome(
                request=request,
                result=result,
                parsed=None,
                provider=route.provider,
                model=provider_model,
                task_type=task_type,
                duration_ms=duration_ms,
            )

        duration_ms = max(0, self.clock_ms() - started)
        if provider_result.status != "ok":
            result = ProcessorResult(
                result_id=provider_result.result_id,
                request_id=request.request_id,
                status="failed",
                output=_safe_json(provider_result.output),
                usage=coerce_usage(provider_result.usage),
                error=provider_result.error or "provider_failed",
            )
            self._journal_result(
                task_id=task_id,
                run_id=run_id,
                step_id=step_id,
                request=request,
                result=result,
                provider=route.provider,
                model=provider_model,
                task_type=task_type,
                duration_ms=duration_ms,
            )
            return ProcessorOutcome(
                request=request,
                result=result,
                parsed=None,
                provider=route.provider,
                model=provider_model,
                task_type=task_type,
                duration_ms=duration_ms,
            )

        text = _result_text(provider_result)
        parsed = parse_json_object(text, max_repair_attempts=self.max_repair_attempts)
        schema_error = None if parsed.value is None else validate_json_schema(parsed.value, schema)
        status = "ok" if parsed.value is not None and schema_error is None else "failed"
        error = parsed.error if parsed.value is None else schema_error
        output: JsonObject = {
            "provider": route.provider,
            "model": provider_model,
            "task_type": task_type,
            "raw_output_preview": _preview(text, 240),
            "raw_output_hash": _hash(text),
            "repaired": parsed.repaired,
            "repair_attempts": parsed.attempts,
        }
        if parsed.value is not None and schema_error is None:
            output["parsed"] = parsed.value
        result = ProcessorResult(
            result_id=provider_result.result_id,
            request_id=request.request_id,
            status=status,
            output=output,
            usage=coerce_usage(provider_result.usage, prompt=prompt, completion=text),
            error=error,
        )
        self._journal_result(
            task_id=task_id,
            run_id=run_id,
            step_id=step_id,
            request=request,
            result=result,
            provider=route.provider,
            model=provider_model,
            task_type=task_type,
            duration_ms=duration_ms,
        )
        return ProcessorOutcome(
            request=request,
            result=result,
            parsed=parsed.value if status == "ok" else None,
            provider=route.provider,
            model=provider_model,
            task_type=task_type,
            duration_ms=duration_ms,
            repaired=parsed.repaired,
            repair_attempts=parsed.attempts,
        )

    def _request(
        self,
        *,
        task_type: str,
        run_id: str,
        context_id: str,
        prompt: str,
        route_provider: str,
        route_model: str,
        timeout_seconds: int,
        route_parameters: JsonObject,
        parameters: JsonObject | None,
    ) -> ProcessorRequest:
        self._counter += 1
        merged: JsonObject = {
            **dict(route_parameters),
            **dict(parameters or {}),
            "task_type": task_type,
            "provider": route_provider,
            "model": route_model,
            "timeout_seconds": timeout_seconds,
        }
        return ProcessorRequest(
            request_id=f"proc-{run_id}-{self._counter}",
            run_id=run_id,
            processor=task_type,
            prompt=prompt,
            context_id=context_id,
            parameters=merged,
        )

    def _journal_request(
        self,
        *,
        task_id: str | None,
        run_id: str,
        step_id: str | None,
        request: ProcessorRequest,
    ) -> None:
        if self.journal is None:
            return
        data = redact_journal_data(_safe_request(request))
        self.journal.append(
            task_id=task_id,
            run_id=run_id,
            step_id=step_id,
            kind="processor_request",
            data=data,
            state_delta={"processor_stage": "request", "processor_task_type": request.processor},
        )

    def _journal_result(
        self,
        *,
        task_id: str | None,
        run_id: str,
        step_id: str | None,
        request: ProcessorRequest,
        result: ProcessorResult,
        provider: str,
        model: str,
        task_type: str,
        duration_ms: int,
    ) -> None:
        if self.journal is None:
            return
        data = redact_journal_data(
            _safe_result(result, provider=provider, model=model, task_type=task_type, duration_ms=duration_ms)
        )
        self.journal.append(
            task_id=task_id,
            run_id=run_id,
            step_id=step_id,
            kind="processor_result",
            data=data,
            state_delta={
                "processor_stage": "result",
                "processor_task_type": task_type,
                "processor_status": result.status,
            },
        )


def validate_json_schema(value: JsonObject, schema: JsonSchema) -> str | None:
    for key, expected in schema.required.items():
        if key not in value:
            return f"missing_required_field:{key}"
        if not _matches_type(value[key], expected):
            return f"invalid_field_type:{key}:{expected}"
    for key, expected in schema.optional.items():
        if key in value and not _matches_type(value[key], expected):
            return f"invalid_field_type:{key}:{expected}"
    return None


def _matches_type(value: object, expected: str) -> bool:
    options = set(expected.split("|"))
    if value is None:
        return "null" in options
    if isinstance(value, bool):
        return "bool" in options
    if isinstance(value, str):
        return "str" in options
    if isinstance(value, (int, float)):
        return "number" in options
    if isinstance(value, list):
        return "list" in options
    if isinstance(value, dict):
        return "dict" in options
    return False


def _result_text(result: ProcessorResult) -> str:
    text = result.output.get("text")
    if isinstance(text, str):
        return text
    return json.dumps(result.output, ensure_ascii=False, sort_keys=True)


def _safe_request(request: ProcessorRequest) -> JsonObject:
    return {
        "request_id": request.request_id,
        "run_id": request.run_id,
        "processor": request.processor,
        "task_type": request.parameters.get("task_type", request.processor),
        "provider": request.parameters.get("provider", ""),
        "model": request.parameters.get("model", ""),
        "context_id": request.context_id,
        "prompt": {
            "preview": _preview(request.prompt, 240),
            "hash": _hash(request.prompt),
            "chars": len(request.prompt),
        },
        "parameters": _safe_json(request.parameters),
        "redaction": {"prompt": "preview_hash_only", "secrets": "redacted"},
    }


def _safe_result(
    result: ProcessorResult,
    *,
    provider: str,
    model: str,
    task_type: str,
    duration_ms: int,
) -> JsonObject:
    return {
        "result_id": result.result_id,
        "request_id": result.request_id,
        "status": result.status,
        "provider": provider,
        "model": model,
        "task_type": task_type,
        "duration_ms": duration_ms,
        "usage": _safe_json(result.usage),
        "output": _safe_json(result.output),
        "error": result.error,
        "redaction": {"raw_output": "preview_hash_only", "secrets": "redacted"},
    }


def _safe_json(data: JsonObject) -> JsonObject:
    safe: JsonObject = {}
    for key, value in data.items():
        lowered = key.lower()
        if _is_secret_key(lowered):
            safe[key] = "[redacted]"
        elif isinstance(value, str):
            safe[key] = _preview(value, 240)
        elif isinstance(value, (int, float, bool)) or value is None:
            safe[key] = value
        elif isinstance(value, list):
            safe[key] = [_safe_value(item) for item in value[:20]]
        elif isinstance(value, dict):
            safe[key] = _safe_json(value)
        else:
            safe[key] = _preview(str(value), 240)
    return safe


def _is_secret_key(lowered: str) -> bool:
    if lowered in {"prompt_tokens", "completion_tokens", "total_tokens"}:
        return False
    return any(
        marker in lowered
        for marker in ("api_key", "apikey", "secret", "authorization", "bearer", "access_token", "refresh_token")
    )


def _safe_value(value: object):
    if isinstance(value, str):
        return _preview(value, 240)
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    if isinstance(value, dict):
        return _safe_json(value)
    if isinstance(value, list):
        return [_safe_value(item) for item in value[:20]]
    return _preview(str(value), 240)


def _preview(text: str, limit: int) -> str:
    normalized = " ".join(text.split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: max(0, limit - 3)] + "..."


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
