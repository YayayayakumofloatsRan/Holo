from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable

from kernel_v3.contracts import JsonObject, ProcessorRequest, ProcessorResult
from kernel_v3.journal import JournalStore
from kernel_v3.journal_redaction import redact_journal_data
from kernel_v3.privacy import contains_secret_like_content
from kernel_v3.processors.contracts import JsonSchema, ProcessorOutcome, ProcessorProvider, ProcessorStreamEvent
from kernel_v3.processors.generation import adapt_generation_parameters
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
        self._provider_circuit: dict[str, JsonObject] = {}
        self._budget_counters: dict[str, JsonObject] = {}

    def stream_events(
        self,
        *,
        task_type: str,
        run_id: str,
        context_id: str,
        prompt: str,
        task_id: str | None = None,
        step_id: str | None = None,
        provider: str | None = None,
        model: str | None = None,
        timeout_seconds: int | None = None,
        parameters: JsonObject | None = None,
    ) -> list[ProcessorStreamEvent]:
        route = self.router.route(task_type, provider=provider, model=model, timeout_seconds=timeout_seconds)
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
        selected = self.providers.get(route.provider)
        if selected is None:
            return self._stream_error(
                request,
                task_id=task_id,
                run_id=run_id,
                step_id=step_id,
                provider=route.provider,
                model=str(request.parameters.get("model") or route.model),
                task_type=task_type,
                error="provider_not_registered",
                delta={"provider": route.provider},
            )
        provider_model = str(request.parameters.get("model") or route.model)
        budget_error = self._processor_budget_error(request, task_id=task_id)
        if budget_error is not None:
            return self._stream_error(
                request,
                task_id=task_id,
                run_id=run_id,
                step_id=step_id,
                provider=route.provider,
                model=provider_model,
                task_type=task_type,
                error="processor_budget_exceeded",
                delta={"budget": budget_error.get("budget", {}), "budget_state": budget_error.get("state", {})},
            )
        circuit = self._provider_circuit.get(route.provider)
        if circuit is not None:
            return self._stream_error(
                request,
                task_id=task_id,
                run_id=run_id,
                step_id=step_id,
                provider=route.provider,
                model=provider_model,
                task_type=task_type,
                error="provider_circuit_open",
                delta={"circuit": circuit},
            )
        boundary_error = _external_private_context_boundary_error(request, provider_name=route.provider, provider=selected)
        if boundary_error is not None:
            return self._stream_error(
                request,
                task_id=task_id,
                run_id=run_id,
                step_id=step_id,
                provider=route.provider,
                model=provider_model,
                task_type=task_type,
                error=boundary_error,
                delta={"boundary": "private_context_external_model"},
            )

        stream_method = getattr(selected, "stream", None)
        started = self.clock_ms()
        events: list[ProcessorStreamEvent] = []
        try:
            if callable(stream_method):
                events = list(stream_method(request))
            else:
                result = selected.run(request)
                events = _events_from_non_streaming_result(request, result)
        except Exception as exc:
            duration_ms = max(0, self.clock_ms() - started)
            error_preview = _preview(str(exc) or type(exc).__name__, 240)
            self._open_provider_circuit(
                route.provider,
                task_type=task_type,
                error=type(exc).__name__,
                error_preview=error_preview,
            )
            events = [
                ProcessorStreamEvent(
                    event_type="stream_error",
                    request_id=request.request_id,
                    sequence=1,
                    delta={"error": type(exc).__name__, "error_preview": error_preview},
                )
            ]
            self._journal_stream_events(
                task_id=task_id,
                run_id=run_id,
                step_id=step_id,
                provider=route.provider,
                model=provider_model,
                task_type=task_type,
                duration_ms=duration_ms,
                events=events,
            )
            return events
        duration_ms = max(0, self.clock_ms() - started)
        self._journal_stream_events(
            task_id=task_id,
            run_id=run_id,
            step_id=step_id,
            provider=route.provider,
            model=provider_model,
            task_type=task_type,
            duration_ms=duration_ms,
            events=events,
        )
        return events

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
            request_model = str(request.parameters.get("model") or route.model)
            result = ProcessorResult(
                result_id=f"result-{request.request_id}",
                request_id=request.request_id,
                status="failed",
                output={"provider": route.provider, "model": request_model},
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
                model=request_model,
                task_type=task_type,
                duration_ms=0,
            )
            return ProcessorOutcome(
                request=request,
                result=result,
                parsed=None,
                provider=route.provider,
                model=request_model,
                task_type=task_type,
                duration_ms=0,
            )

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
        provider_model = str(request.parameters.get("model") or route.model)
        self._journal_request(task_id=task_id, run_id=run_id, step_id=step_id, request=request)
        budget_error = self._processor_budget_error(request, task_id=task_id)
        if budget_error is not None:
            result = ProcessorResult(
                result_id=f"result-{request.request_id}",
                request_id=request.request_id,
                status="failed",
                output={
                    "provider": route.provider,
                    "model": provider_model,
                    "task_type": task_type,
                    "budget": budget_error.get("budget", {}),
                    "budget_state": budget_error.get("state", {}),
                    "reason": budget_error.get("reason"),
                },
                usage={},
                error="processor_budget_exceeded",
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
                duration_ms=0,
            )
            return ProcessorOutcome(
                request=request,
                result=result,
                parsed=None,
                provider=route.provider,
                model=provider_model,
                task_type=task_type,
                duration_ms=0,
            )
        circuit = self._provider_circuit.get(route.provider)
        if circuit is not None:
            result = ProcessorResult(
                result_id=f"result-{request.request_id}",
                request_id=request.request_id,
                status="failed",
                output={
                    "provider": route.provider,
                    "model": provider_model,
                    "circuit": "provider_unavailable",
                    "previous_error": circuit.get("error"),
                    "previous_error_preview": circuit.get("error_preview"),
                    "previous_task_type": circuit.get("task_type"),
                },
                usage={},
                error="provider_circuit_open",
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
                duration_ms=0,
            )
            return ProcessorOutcome(
                request=request,
                result=result,
                parsed=None,
                provider=route.provider,
                model=provider_model,
                task_type=task_type,
                duration_ms=0,
            )
        boundary_error = _external_private_context_boundary_error(request, provider_name=route.provider, provider=selected)
        if boundary_error is not None:
            result = ProcessorResult(
                result_id=f"result-{request.request_id}",
                request_id=request.request_id,
                status="failed",
                output={
                    "provider": route.provider,
                    "model": provider_model,
                    "boundary": "private_context_external_model",
                    "redaction": {"prompt": "not_sent_to_provider"},
                },
                usage={},
                error=boundary_error,
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
                duration_ms=0,
            )
            return ProcessorOutcome(
                request=request,
                result=result,
                parsed=None,
                provider=route.provider,
                model=provider_model,
                task_type=task_type,
                duration_ms=0,
            )
        started = self.clock_ms()
        provider_result: ProcessorResult | None = None
        try:
            provider_result = selected.run(request)
        except Exception as exc:  # concrete providers normalize availability, but host catches all provider faults.
            duration_ms = max(0, self.clock_ms() - started)
            error_preview = _preview(str(exc) or type(exc).__name__, 240)
            result = ProcessorResult(
                result_id=f"result-{request.request_id}",
                request_id=request.request_id,
                status="failed",
                output={
                    "provider": route.provider,
                    "model": provider_model,
                    "error_type": type(exc).__name__,
                    "error_message_preview": error_preview,
                },
                usage={},
                error=type(exc).__name__,
            )
            self._record_processor_budget_usage(request, task_id=task_id, result=result)
            self._open_provider_circuit(
                route.provider,
                task_type=task_type,
                error=type(exc).__name__,
                error_preview=error_preview,
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
            output = _safe_json(provider_result.output)
            result = ProcessorResult(
                result_id=provider_result.result_id,
                request_id=request.request_id,
                status="failed",
                output=output,
                usage=coerce_usage(provider_result.usage),
                error=provider_result.error or "provider_failed",
            )
            self._record_processor_budget_usage(request, task_id=task_id, result=result)
            if _is_provider_availability_error(provider_result.error or "", output):
                self._open_provider_circuit(
                    route.provider,
                    task_type=task_type,
                    error=provider_result.error or "provider_failed",
                    error_preview=_provider_error_preview(output),
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
        raw_text = _bounded_processor_raw_text(text)
        parsed = parse_json_object(text, max_repair_attempts=self.max_repair_attempts)
        parsed_value = (
            _normalize_processor_json_for_schema(parsed.value, schema)
            if isinstance(parsed.value, dict)
            else parsed.value
        )
        schema_error = None if parsed_value is None else validate_json_schema(parsed_value, schema)
        status = "ok" if parsed_value is not None and schema_error is None else "failed"
        error = parsed.error if parsed_value is None else schema_error
        output: JsonObject = {
            "provider": route.provider,
            "model": provider_model,
            "task_type": task_type,
            "raw_output_preview": _preview(text, 240),
            "raw_output_hash": _hash(text),
            "repaired": parsed.repaired,
            "repair_attempts": parsed.attempts,
        }
        if parsed_value is not None and schema_error is None:
            output["parsed"] = parsed_value
        result = ProcessorResult(
            result_id=provider_result.result_id,
            request_id=request.request_id,
            status=status,
            output=output,
            usage=coerce_usage(provider_result.usage, prompt=prompt, completion=text),
            error=error,
        )
        self._record_processor_budget_usage(request, task_id=task_id, result=result)
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
            parsed=parsed_value if status == "ok" else None,
            provider=route.provider,
            model=provider_model,
            task_type=task_type,
            duration_ms=duration_ms,
            repaired=parsed.repaired,
            repair_attempts=parsed.attempts,
            raw_text=raw_text,
        )

    def _processor_budget_error(self, request: ProcessorRequest, *, task_id: str | None) -> JsonObject | None:
        budget = _processor_budget(request)
        if not budget:
            return None
        state = self._processor_budget_state(request, task_id=task_id)
        max_prompt_chars = _positive_budget_int(budget.get("max_prompt_chars_per_call"))
        if max_prompt_chars is not None and len(request.prompt) > max_prompt_chars:
            return {
                "reason": "max_prompt_chars_per_call",
                "budget": budget,
                "state": {**state, "prompt_chars": len(request.prompt)},
            }
        max_calls = _positive_budget_int(budget.get("max_calls_per_task"))
        if max_calls is not None and int(state.get("calls") or 0) >= max_calls:
            return {"reason": "max_calls_per_task", "budget": budget, "state": state}
        max_tokens = _positive_budget_int(budget.get("max_total_tokens_per_task"))
        if max_tokens is not None and int(state.get("total_tokens") or 0) >= max_tokens:
            return {"reason": "max_total_tokens_per_task", "budget": budget, "state": state}
        return None

    def _processor_budget_state(self, request: ProcessorRequest, *, task_id: str | None) -> JsonObject:
        key = _processor_budget_key(request, task_id=task_id)
        state = self._budget_counters.setdefault(key, {"calls": 0, "total_tokens": 0})
        return dict(state)

    def _record_processor_budget_usage(
        self,
        request: ProcessorRequest,
        *,
        task_id: str | None,
        result: ProcessorResult,
    ) -> None:
        if not _processor_budget(request):
            return
        key = _processor_budget_key(request, task_id=task_id)
        state = self._budget_counters.setdefault(key, {"calls": 0, "total_tokens": 0})
        state["calls"] = int(state.get("calls") or 0) + 1
        state["total_tokens"] = int(state.get("total_tokens") or 0) + _usage_total_tokens(result.usage)

    def _open_provider_circuit(self, provider: str, *, task_type: str, error: str, error_preview: str | None) -> None:
        self._provider_circuit.setdefault(
            provider,
            {
                "task_type": task_type,
                "error": error,
                "error_preview": error_preview,
            },
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
        merged = adapt_generation_parameters(task_type=task_type, prompt=prompt, parameters=merged)
        merged["task_type"] = task_type
        merged["provider"] = route_provider
        merged.setdefault("model", route_model)
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

    def _journal_stream_events(
        self,
        *,
        task_id: str | None,
        run_id: str,
        step_id: str | None,
        provider: str,
        model: str,
        task_type: str,
        duration_ms: int,
        events: list[ProcessorStreamEvent],
    ) -> None:
        if self.journal is None:
            return
        self.journal.append(
            task_id=task_id,
            run_id=run_id,
            step_id=step_id,
            kind="processor_stream",
            data=redact_journal_data(
                {
                    "provider": provider,
                    "model": model,
                    "task_type": task_type,
                    "duration_ms": duration_ms,
                    "event_count": len(events),
                    "events": [event.to_dict() for event in events],
                }
            ),
            state_delta={
                "processor_stage": "stream",
                "processor_task_type": task_type,
                "processor_stream_event_count": len(events),
            },
        )

    def _stream_error(
        self,
        request: ProcessorRequest,
        *,
        task_id: str | None,
        run_id: str,
        step_id: str | None,
        provider: str,
        model: str,
        task_type: str,
        error: str,
        delta: JsonObject,
    ) -> list[ProcessorStreamEvent]:
        event = ProcessorStreamEvent(
            event_type="stream_error",
            request_id=request.request_id,
            sequence=1,
            delta={"error": error, **dict(delta)},
        )
        self._journal_stream_events(
            task_id=task_id,
            run_id=run_id,
            step_id=step_id,
            provider=provider,
            model=model,
            task_type=task_type,
            duration_ms=0,
            events=[event],
        )
        return [event]


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


def _normalize_processor_json_for_schema(value: JsonObject, schema: JsonSchema) -> JsonObject:
    if schema.name == "finance.numeric_judge":
        normalized = dict(value)
        if "reason_summary" not in normalized:
            for alias in ("reason", "rationale", "explanation", "summary"):
                alias_value = normalized.get(alias)
                if isinstance(alias_value, str) and alias_value.strip():
                    normalized["reason_summary"] = alias_value.strip()
                    break
            else:
                normalized["reason_summary"] = "The model returned a numeric judgment without a dedicated reason_summary field."
        decision = str(normalized.get("decision") or "").strip()
        if "answer_addresses_question" not in normalized:
            normalized["answer_addresses_question"] = decision not in {"continue_work", "fail_with_limitations"}
        for key in (
            "core_numeric_claims",
            "non_core_numeric_claims",
            "unsupported_core_values",
            "missing_slots",
            "candidate_supported_values",
            "limitations",
        ):
            if key not in normalized or normalized.get(key) is None:
                normalized[key] = []
        if "repair_instruction" not in normalized or normalized.get("repair_instruction") is None:
            normalized["repair_instruction"] = ""
        if "requires_more_work" not in normalized:
            normalized["requires_more_work"] = decision == "continue_work"
        if "confidence" in normalized and not isinstance(normalized.get("confidence"), (int, float)):
            try:
                normalized["confidence"] = float(str(normalized.get("confidence")).strip())
            except ValueError:
                normalized.pop("confidence", None)
        return normalized
    if schema.name == "task.compile":
        normalized = dict(value)
        if "reason_summary" not in normalized:
            for alias in ("reason", "rationale", "explanation", "summary"):
                alias_value = normalized.get(alias)
                if isinstance(alias_value, str) and alias_value.strip():
                    normalized["reason_summary"] = alias_value.strip()
                    break
        return normalized
    if schema.name == "finance.slot_bind":
        normalized = dict(value)
        if "formula_requests" not in normalized or normalized.get("formula_requests") is None:
            for alias in ("formula_request", "formulas", "calculations", "calculator_calls", "tool_calls"):
                alias_value = normalized.get(alias)
                if isinstance(alias_value, list):
                    normalized["formula_requests"] = alias_value
                    break
                if isinstance(alias_value, dict):
                    normalized["formula_requests"] = [alias_value]
                    break
        if "reason_summary" not in normalized:
            for alias in ("reason", "rationale", "explanation", "summary"):
                alias_value = normalized.get(alias)
                if isinstance(alias_value, str) and alias_value.strip():
                    normalized["reason_summary"] = alias_value.strip()
                    break
            else:
                normalized["reason_summary"] = "The model returned slot bindings without a dedicated reason_summary field."
        for key in ("slot_bindings", "formula_requests", "missing_slots"):
            if key not in normalized or normalized.get(key) is None:
                normalized[key] = []
        if "decision" not in normalized or not isinstance(normalized.get("decision"), str):
            normalized["decision"] = "ready" if normalized.get("formula_requests") else "needs_more_evidence"
        if "next_action" in normalized:
            next_action = normalized.get("next_action")
            if next_action is None or next_action == "":
                normalized.pop("next_action", None)
            elif isinstance(next_action, str):
                normalized["next_action"] = {"tool": next_action.strip(), "reason": ""}
            elif isinstance(next_action, list):
                first = next((item for item in next_action if isinstance(item, dict) or isinstance(item, str)), None)
                if isinstance(first, dict):
                    normalized["next_action"] = first
                elif isinstance(first, str):
                    normalized["next_action"] = {"tool": first.strip(), "reason": ""}
                else:
                    normalized.pop("next_action", None)
            elif not isinstance(next_action, dict):
                normalized.pop("next_action", None)
        return normalized
    return value


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


def _processor_budget(request: ProcessorRequest) -> JsonObject:
    value = request.parameters.get("processor_budget")
    if not isinstance(value, dict):
        return {}
    return {str(key): item for key, item in value.items()}


def _events_from_non_streaming_result(
    request: ProcessorRequest,
    result: ProcessorResult,
) -> list[ProcessorStreamEvent]:
    if result.status != "ok":
        return [
            ProcessorStreamEvent(
                event_type="stream_error",
                request_id=request.request_id,
                sequence=1,
                delta={
                    "status": result.status,
                    "error": result.error or "provider_failed",
                    "output": _safe_json(result.output),
                },
            )
        ]
    text = _result_text(result)
    return [
        ProcessorStreamEvent(
            event_type="stream_start",
            request_id=request.request_id,
            sequence=1,
            delta={"fallback": "non_streaming"},
        ),
        ProcessorStreamEvent(
            event_type="content_delta",
            request_id=request.request_id,
            sequence=2,
            delta={"text": text},
        ),
        ProcessorStreamEvent(
            event_type="stream_end",
            request_id=request.request_id,
            sequence=3,
            delta={"status": "ok", "usage": coerce_usage(result.usage, prompt=request.prompt, completion=text)},
        ),
    ]


def _processor_budget_key(request: ProcessorRequest, *, task_id: str | None) -> str:
    if task_id:
        return f"task:{task_id}"
    if request.run_id:
        return f"run:{request.run_id}"
    return f"request:{request.request_id}"


def _positive_budget_int(value: object) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _usage_total_tokens(usage: JsonObject) -> int:
    for key in ("total_tokens", "tokens"):
        value = usage.get(key)
        if isinstance(value, int) and value > 0:
            return value
        if isinstance(value, float) and value > 0:
            return int(value)
    prompt = usage.get("prompt_tokens")
    completion = usage.get("completion_tokens")
    total = 0
    if isinstance(prompt, (int, float)) and prompt > 0:
        total += int(prompt)
    if isinstance(completion, (int, float)) and completion > 0:
        total += int(completion)
    return total


def _result_text(result: ProcessorResult) -> str:
    text = result.output.get("text")
    if isinstance(text, str):
        return text
    return json.dumps(result.output, ensure_ascii=False, sort_keys=True)


def _bounded_processor_raw_text(text: str, *, limit: int = 20000) -> str:
    value = str(text or "")
    if len(value) <= limit:
        return value
    return value[:limit]


def _external_private_context_boundary_error(
    request: ProcessorRequest,
    *,
    provider_name: str,
    provider: ProcessorProvider,
) -> str | None:
    if _private_context_allowed(request):
        return None
    if not _is_external_model_provider(provider_name, provider):
        return None
    if contains_secret_like_content(request.prompt):
        return "private_context_external_model_blocked:secret_like_content"
    if _has_private_context_marker(request.prompt):
        return "private_context_external_model_blocked:sensitive_context_marker"
    return None


def _private_context_allowed(request: ProcessorRequest) -> bool:
    value = request.parameters.get("allow_private_context_to_external_model")
    return bool(value is True or str(value).lower() in {"1", "true", "yes", "allow"})


def _is_external_model_provider(provider_name: str, provider: ProcessorProvider) -> bool:
    name = str(getattr(provider, "name", provider_name) or provider_name).lower()
    if name.startswith("fake") or name in {"capture", "local", "local_cli", "local_model"}:
        return False
    if bool(getattr(provider, "local_only", False)):
        return False
    return True


def _has_private_context_marker(prompt: str) -> bool:
    compact = prompt.replace(" ", "").lower()
    markers = (
        '"privacy_class":"sensitive"',
        '"private_context":true',
        '"external_model_allowed":false',
        '"allow_external_model":false',
        "[private_context]",
    )
    return any(marker in compact for marker in markers)


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


def _is_provider_availability_error(error: str, output: JsonObject) -> bool:
    text = " ".join(
        str(value)
        for value in (
            error,
            output.get("error"),
            output.get("error_type"),
            output.get("error_message_preview"),
            output.get("reason"),
        )
        if isinstance(value, str)
    ).lower()
    if not text:
        return False
    return any(
        token in text
        for token in (
            "network error",
            "temporary failure",
            "name resolution",
            "timeout",
            "timed out",
            "connection refused",
            "connection reset",
            "provider_disabled",
            "provider unavailable",
            "service unavailable",
        )
    )


def _provider_error_preview(output: JsonObject) -> str | None:
    for key in ("error_message_preview", "error", "reason"):
        value = output.get(key)
        if isinstance(value, str) and value:
            return _preview(value, 240)
    return None


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
